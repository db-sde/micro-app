"""Write a case's truth.json from its corrected WordPress post (read-only).

    cd backend
    python -m evals.fetch_truth jamia-mba            # one case (uses case.json post_id)
    python -m evals.fetch_truth --all                # every case with a post_id
    python -m evals.fetch_truth jamia-mba --from-export export.json   # no network

GET /wp-json/wp/v2/{type}/{id}?context=edit with the app's WordPress
credentials, so draft posts can be read. GET only: this never writes to
WordPress.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx

from evals.cases import Case, load_cases


def truth_from_post(post: dict[str, Any], post_type: str) -> dict[str, Any]:
    title = post.get("title")
    if isinstance(title, dict):
        title = title.get("raw") or title.get("rendered")
    return {"post_id": post.get("id"), "post_type": post_type, "status": post.get("status"), "title": title,
            "modified": post.get("modified"), "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "acf": post.get("acf") or {}}


def fetch_post(post_type: str, post_id: int, client: httpx.Client | None = None) -> dict[str, Any]:
    from pipeline import wordpress_client as wc

    if not wc.is_configured():
        raise RuntimeError("WordPress credentials are not configured in backend/.env.")
    url = f"{wc._site_url()}/wp-json/wp/v2/{wc.get_post_type(post_type)}/{post_id}"
    params = {"context": "edit", "_fields": "id,title,status,modified,acf"}
    if client is None:
        with httpx.Client(timeout=30.0) as c:
            resp = c.get(url, params=params, auth=wc._auth())
    else:
        resp = client.get(url, params=params, auth=wc._auth())
    if resp.status_code >= 400:
        raise RuntimeError(f"GET {url} -> HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


def write_truth(case: Case, truth: dict[str, Any]) -> Path:
    case.truth_path.write_text(json.dumps(truth, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return case.truth_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--from-export", type=Path, help="a post JSON (or list of posts) exported from WordPress")
    args = parser.parse_args(argv)
    cases = load_cases(ids=None if args.all else args.cases)
    if not args.all and not args.cases:
        parser.error("name one or more cases, or --all")
    for case in cases:
        if args.from_export:
            data = json.loads(args.from_export.read_text(encoding="utf-8"))
            posts = data if isinstance(data, list) else [data]
            post = next((p for p in posts if p.get("id") == case.post_id), posts[0] if len(posts) == 1 else None)
            if post is None:
                print(f"{case.case_id}: post {case.post_id} not in the export", file=sys.stderr)
                continue
        else:
            if not case.post_id:
                print(f"{case.case_id}: no post_id in case.json, skipped", file=sys.stderr)
                continue
            post = fetch_post(case.post_type or case.page_type, case.post_id)
        path = write_truth(case, truth_from_post(post, case.post_type or case.page_type))
        print(f"{case.case_id}: {len(post.get('acf') or {})} fields, status={post.get('status')} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
