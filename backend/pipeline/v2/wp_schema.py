"""The live WordPress ACF schema, per post type.

Read with an unauthenticated OPTIONS /wp-json/wp/v2/{type} (read-only).
A trimmed copy is committed under acf/wp_schema/ so tests and offline runs
never need the network. At runtime the live schema is cached on disk for
a day and the committed snapshot is the fallback.

Refresh the committed snapshot:

    cd backend && python -m pipeline.v2.wp_schema --refresh
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("degreebaba.v2.wp_schema")

PAGE_TYPES = ("university", "course", "specialization")
SNAPSHOT_DIR = Path(__file__).resolve().parents[2] / "acf" / "wp_schema"
CACHE_DIR = Path(os.getenv("V2_SCHEMA_CACHE_DIR", str(Path(__file__).resolve().parents[2] / ".cache" / "wp_schema")))
CACHE_TTL_SECONDS = 24 * 3600
DEFAULT_SITE = "https://degreebaba.demo-nexevo.in"


def _trim_property(prop: dict[str, Any]) -> dict[str, Any]:
    """Keep only what the extraction schema needs: type, description, sub-fields."""
    out: dict[str, Any] = {"type": prop.get("type")}
    if prop.get("description"):
        out["description"] = prop["description"]
    items = prop.get("items")
    if isinstance(items, dict) and isinstance(items.get("properties"), dict):
        out["sub_fields"] = {k: _trim_property(v) for k, v in items["properties"].items() if isinstance(v, dict)}
    return out


def trim_options_response(body: dict[str, Any]) -> dict[str, Any]:
    """OPTIONS response -> {field_name: {type, description?, sub_fields?}}."""
    props = body.get("schema", {}).get("properties", {}).get("acf", {}).get("properties", {})
    if not isinstance(props, dict) or not props:
        raise ValueError("OPTIONS response has no acf.properties")
    return {k: _trim_property(v) for k, v in sorted(props.items()) if isinstance(v, dict)}


def fetch_live(post_type: str, site: str | None = None, client: httpx.Client | None = None) -> dict[str, Any]:
    """Fetch and trim one post type's live ACF schema (read-only OPTIONS)."""
    base = (site or os.getenv("WORDPRESS_SITE_URL") or DEFAULT_SITE).rstrip("/")
    url = f"{base}/wp-json/wp/v2/{post_type}"
    if client is None:
        with httpx.Client(timeout=30.0) as c:
            resp = c.options(url)
    else:
        resp = client.options(url)
    if resp.status_code >= 400:
        raise RuntimeError(f"OPTIONS {url} returned HTTP {resp.status_code}")
    return trim_options_response(resp.json())


def load_snapshot(page_type: str) -> dict[str, Any]:
    """The committed snapshot for a page type."""
    data = json.loads((SNAPSHOT_DIR / f"{page_type}.json").read_text(encoding="utf-8"))
    return data["acf"]


def load_schema(page_type: str, live: bool | None = None) -> dict[str, Any]:
    """The live schema (day-cached on disk), falling back to the snapshot.

    Live lookup runs only when V2_LIVE_SCHEMA=1 (or live=True), so tests
    and offline runs stay deterministic.
    """
    if live is None:
        live = os.getenv("V2_LIVE_SCHEMA", "") == "1"
    if not live:
        return load_snapshot(page_type)
    cache_file = CACHE_DIR / f"{page_type}.json"
    try:
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime < CACHE_TTL_SECONDS:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        acf = fetch_live(page_type)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(acf, indent=1, ensure_ascii=False), encoding="utf-8")
        return acf
    except Exception as exc:  # network, firewall, unexpected shape
        logger.warning("LIVE_SCHEMA_UNAVAILABLE: %s (%s); using committed snapshot", page_type, exc)
        return load_snapshot(page_type)


def write_snapshot(page_type: str, acf: dict[str, Any], site: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{page_type}.json"
    body = {
        "source": f"OPTIONS {site.rstrip('/')}/wp-json/wp/v2/{page_type}",
        "fetched_at": time.strftime("%Y-%m-%d"),
        "acf": acf,
    }
    path.write_text(json.dumps(body, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _main(argv: list[str]) -> int:
    if "--refresh" not in argv:
        print(__doc__)
        return 2
    site = os.getenv("WORDPRESS_SITE_URL") or DEFAULT_SITE
    for page_type in PAGE_TYPES:
        acf = fetch_live(page_type, site)
        print(f"{page_type}: {len(acf)} fields -> {write_snapshot(page_type, acf, site)}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
