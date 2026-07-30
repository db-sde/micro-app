"""
WordPress REST API client — media uploads + ACF post publishing.

Auth: WordPress Application Passwords (Basic Auth). Configure via .env:

    WORDPRESS_SITE_URL=https://your-site.com
    WORDPRESS_APP_USER=admin
    WORDPRESS_APP_PASSWORD=xxxx xxxx xxxx xxxx xxxx xxxx

Optional per-page-type CPT slug overrides (defaults to the page_type name
itself, e.g. "university" -> CPT slug "university"):

    WORDPRESS_POST_TYPE_UNIVERSITY=university
    WORDPRESS_POST_TYPE_COURSE=course
    WORDPRESS_POST_TYPE_SPECIALIZATION=specialization

Assumes the target site exposes ACF fields over REST (ACF PRO 5.11+ with
"Show in REST API" enabled per field group, or the ACF to REST API plugin) —
publish_payload() sends field values under the "acf" key on create/update.

Public API
----------
is_configured()                                   -> bool
upload_media(file_bytes, filename, content_type)  -> dict {id, source_url, link}
publish_payload(payload, page_type, status, post_id=None) -> dict
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("degreebaba.wordpress")

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _site_url() -> str:
    url = os.getenv("WORDPRESS_SITE_URL", "").strip()
    return url.rstrip("/")


def _auth() -> tuple[str, str]:
    user = os.getenv("WORDPRESS_APP_USER", "").strip()
    password = os.getenv("WORDPRESS_APP_PASSWORD", "").strip()
    return user, password


def is_configured() -> bool:
    """True if enough WordPress credentials are present to attempt API calls."""
    user, password = _auth()
    return bool(_site_url() and user and password)


def get_post_type(page_type: str) -> str:
    """Resolve the WP custom-post-type slug for a given page_type.

    Defaults to the page_type name itself; overridable per-type via env var
    so a mismatched CPT slug can be fixed without a code change.
    """
    env_key = f"WORDPRESS_POST_TYPE_{page_type.upper()}"
    return os.getenv(env_key, "").strip() or page_type


def _raise_for_wp_error(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        try:
            body = resp.json()
            message = body.get("message", resp.text)
        except Exception:
            message = resp.text
        raise RuntimeError(
            f"WordPress API error ({resp.status_code}): {message}"
        )


# ────────────────────────── media upload ──────────────────────────


def upload_media(file_bytes: bytes, filename: str, content_type: str) -> dict[str, Any]:
    """Upload an image to the WordPress media library.

    Returns ``{"id": int, "source_url": str, "link": str}``.
    Raises RuntimeError if WordPress is not configured or the call fails.
    """
    if not is_configured():
        raise RuntimeError(
            "WordPress is not configured (WORDPRESS_SITE_URL / "
            "WORDPRESS_APP_USER / WORDPRESS_APP_PASSWORD missing)."
        )

    url = f"{_site_url()}/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": content_type,
    }

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(
            url,
            content=file_bytes,
            headers=headers,
            auth=_auth(),
        )
    _raise_for_wp_error(resp)

    data = resp.json()
    logger.info("WP_MEDIA_UPLOADED: id=%s url=%s", data.get("id"), data.get("source_url"))
    return {
        "id": data.get("id"),
        "source_url": data.get("source_url"),
        "link": data.get("link"),
    }


# ────────────────────────── post publishing ──────────────────────────


def _build_title(payload: dict[str, Any], page_type: str, fallback: str) -> str:
    for key in ("university_name", "program_name", "spec_name", "course_name"):
        val = payload.get(key)
        if val and isinstance(val, str):
            return val
    return fallback


def publish_payload(
    payload: dict[str, Any],
    page_type: str,
    status: str = "draft",
    post_id: int | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    """Create or update a WordPress post populated with ACF field values.

    Parameters
    ----------
    payload : dict
        The final ACF JSON payload (as produced by ``build_json_output`` —
        may include a ``_meta`` key, which is stripped before sending).
    page_type : str
        ``"university"`` / ``"course"`` / ``"specialization"``.
    status : str
        WordPress post status — ``"draft"`` (default) or ``"publish"``.
    post_id : int | None
        If given, updates that existing post instead of creating a new one.
    title : str | None
        Explicit post title; otherwise derived from the payload.

    Returns
    -------
    dict
        ``{"id": int, "link": str, "edit_link": str, "status": str}``
    """
    if not is_configured():
        raise RuntimeError(
            "WordPress is not configured (WORDPRESS_SITE_URL / "
            "WORDPRESS_APP_USER / WORDPRESS_APP_PASSWORD missing)."
        )

    if status not in ("draft", "publish", "pending"):
        raise ValueError(f"Invalid status: {status!r}. Must be draft, publish, or pending.")

    post_type = get_post_type(page_type)
    acf_fields = {k: v for k, v in payload.items() if k != "_meta"}
    post_title = title or _build_title(payload, page_type, fallback=f"Untitled {page_type}")

    body = {
        "title": post_title,
        "status": status,
        "acf": acf_fields,
    }

    base_url = f"{_site_url()}/wp-json/wp/v2/{post_type}"
    url = f"{base_url}/{post_id}" if post_id else base_url

    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(url, json=body, auth=_auth())
    _raise_for_wp_error(resp)

    data = resp.json()
    wp_id = data.get("id")
    site = _site_url()
    result = {
        "id": wp_id,
        "link": data.get("link"),
        "edit_link": f"{site}/wp-admin/post.php?post={wp_id}&action=edit",
        "status": data.get("status", status),
    }
    logger.info(
        "WP_PUBLISHED: page_type=%s post_type=%s id=%s status=%s",
        page_type, post_type, wp_id, result["status"],
    )
    return result
