"""What a payload would become on WordPress, without touching WordPress.

Runs the real, unmodified wordpress_client.publish_payload against an
in-memory fake site (httpx.MockTransport) and captures the ACF body it
would send. Truth comes from corrected WordPress posts, so scoring
happens in WordPress's field names.

mode="published": every publish-time step, as /publish runs today.
mode="raw":       _polish_for_wordpress, _syllabus_extras and
                  _placement_extras are switched off, which measures what
                  the extraction itself got right. Renames, fee-tier
                  mapping and the key filter still run (they are mapping,
                  not repair).
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from typing import Any

import httpx

from pipeline import wordpress_client as wc
from pipeline.v2 import wp_schema

FAKE_SITE = "https://wp.eval.invalid"
_NEW_POST_ID = 900001


class _HttpxShim:
    """wordpress_client's `httpx`, with Client bound to the fake site."""

    def __init__(self, transport: httpx.MockTransport) -> None:
        self._transport = transport

    def Client(self, *args, **kwargs):  # noqa: N802 - mirrors httpx.Client
        kwargs.pop("transport", None)
        return httpx.Client(*args, transport=self._transport, **kwargs)

    def __getattr__(self, name: str):
        return getattr(httpx, name)


def _options_body(post_type: str) -> dict[str, Any]:
    try:
        acf = wp_schema.load_snapshot(post_type)
    except FileNotFoundError:
        acf = {}
    return {"schema": {"properties": {"acf": {"properties": {k: {"type": v.get("type")} for k, v in acf.items()}}}}}


class FakeWordPress:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        self.requests.append({"method": request.method, "path": path, "json": body})
        m = re.match(r"^/wp-json/wp/v2/([^/]+)(?:/(\d+))?$", path)
        if not m:
            return httpx.Response(404, json={"message": "not found"})
        kind, post_id = m.group(1), m.group(2)
        if request.method == "OPTIONS":
            return httpx.Response(200, json=_options_body(kind))
        if request.method == "GET":
            return httpx.Response(200, json=[], headers={"X-WP-TotalPages": "1"})
        if request.method == "POST":
            new_id = int(post_id) if post_id else _NEW_POST_ID
            return httpx.Response(200, json={"id": new_id, "link": f"{FAKE_SITE}/{kind}/{new_id}/", "status": "draft"})
        return httpx.Response(405, json={})

    def sent_acf(self) -> dict[str, Any]:
        updates = [r for r in self.requests if r["method"] == "POST" and (r["json"] or {}).get("acf") is not None]
        return updates[-1]["json"]["acf"] if updates else {}

    def sent_title(self) -> str | None:
        for r in self.requests:
            if r["method"] == "POST" and (r["json"] or {}).get("title"):
                return r["json"]["title"]
        return None


@contextmanager
def _fake_site(fake: FakeWordPress, raw: bool):
    saved_env = {k: os.environ.get(k) for k in ("WORDPRESS_SITE_URL", "WORDPRESS_APP_USER", "WORDPRESS_APP_PASSWORD")}
    saved = {"httpx": wc.httpx, "_polish_for_wordpress": wc._polish_for_wordpress,
             "_syllabus_extras": wc._syllabus_extras, "_placement_extras": wc._placement_extras}
    os.environ.update({"WORDPRESS_SITE_URL": FAKE_SITE, "WORDPRESS_APP_USER": "eval", "WORDPRESS_APP_PASSWORD": "eval"})
    wc.httpx = _HttpxShim(fake.transport)
    if raw:
        wc._polish_for_wordpress = lambda acf, page_type: acf
        wc._syllabus_extras = lambda acf, page_type: {}
        wc._placement_extras = lambda acf, page_type: {}
    for cache in (wc._post_title_cache, wc._post_title_cache_ts, wc._term_id_cache):
        cache.clear()
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(wc, name, value)
        for k, v in saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        for cache in (wc._post_title_cache, wc._post_title_cache_ts, wc._term_id_cache):
            cache.clear()


def project(payload: dict[str, Any], page_type: str, mode: str = "published") -> dict[str, Any]:
    """-> {"acf": {...}, "title": str, "requests": int}. Never reaches the network."""
    if mode not in ("published", "raw"):
        raise ValueError(mode)
    fake = FakeWordPress()
    with _fake_site(fake, raw=(mode == "raw")):
        wc.publish_payload(json.loads(json.dumps(payload)), page_type, status="draft")
    return {"acf": fake.sent_acf(), "title": fake.sent_title(), "requests": len(fake.requests)}
