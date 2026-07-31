"""
WordPress REST API client — ACF post publishing.

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

Image fields (hero_image, certificate_image) are populated separately, via
pipeline.cloudinary_client, as plain URL strings — but a native ACF
"Image" field type requires an actual WordPress media attachment ID, not
an external URL, or WordPress rejects the whole acf object with
"acf[<field>] requires a valid attachment ID". publish_payload() handles
this by downloading the image from its Cloudinary URL and side-loading it
into the WordPress media library at publish time, then sending the
resulting attachment ID instead of the URL. Images are optional — a field
with no uploaded image (null) is left as null, no conversion attempted.

Public API
----------
is_configured()                                           -> bool
publish_payload(payload, page_type, status, post_id=None)  -> dict
"""

from __future__ import annotations

import logging
import mimetypes
import os
import re
from typing import Any

import httpx
from dotenv import load_dotenv

from acf.fields import get_valid_field_keys, get_field_type, IMAGE

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
        except Exception:
            body = None

        if body is None:
            message = resp.text
        else:
            # WP's top-level "message" for rest_invalid_param is almost
            # always a generic "Invalid parameter(s): acf" with no field
            # name — the actual reason is nested one level deeper, in
            # data.params (field -> short reason) and/or data.details
            # (field -> {code, message}). Surface both so the real cause
            # (which ACF field, and why) is visible instead of guessing.
            message = body.get("message", resp.text)
            data = body.get("data") or {}
            if isinstance(data, dict):
                extras: list[str] = []
                params = data.get("params")
                if isinstance(params, dict):
                    extras.extend(f"{k}: {v}" for k, v in params.items())
                details = data.get("details")
                if isinstance(details, dict):
                    for k, v in details.items():
                        if isinstance(v, dict):
                            detail_msg = v.get("message") or v.get("code")
                            if detail_msg:
                                extras.append(f"{k}: {detail_msg}")
                if extras:
                    message = f"{message} — {'; '.join(extras)}"

        raise RuntimeError(
            f"WordPress API error ({resp.status_code}): {message}"
        )


# ────────────────────────── post publishing ──────────────────────────


def _build_title(payload: dict[str, Any], page_type: str, fallback: str) -> str:
    for key in ("university_name", "program_name", "spec_name"):
        val = payload.get(key)
        if val and isinstance(val, str):
            return val
    return fallback


def _upload_media_from_url(url: str, filename_hint: str) -> int:
    """Download an image from `url` and side-load it into the WordPress
    media library, returning the resulting attachment ID.

    A native ACF "Image" field type only accepts a WordPress attachment ID,
    never an external URL — this is how publish_payload() satisfies that
    for fields whose canonical copy lives on Cloudinary.
    """
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        img_resp = client.get(url)
    if img_resp.status_code >= 400:
        raise RuntimeError(
            f"Could not download image from {url} (HTTP {img_resp.status_code})"
        )

    content = img_resp.content
    content_type = img_resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    filename = f"{filename_hint}{ext}"

    media_url = f"{_site_url()}/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": content_type,
    }
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.post(media_url, content=content, headers=headers, auth=_auth())
    _raise_for_wp_error(resp)

    data = resp.json()
    attachment_id = data.get("id")
    logger.info("WP_MEDIA_SIDELOADED: id=%s from_url=%s", attachment_id, url)
    return attachment_id


# Reconciliation against the real WordPress ACF field group exports
# (2026-07-31). Three categories of mismatch between our internal schema
# and WordPress's actual registered field names:
#
# 1. hero_image doesn't exist as an ACF field on ANY of the three page
#    types — all three CPTs support "thumbnail" natively, so it's handled
#    separately below as the WordPress native Featured Image
#    (featured_media), never sent inside "acf" at all.
#
# 2. Simple renames — the field exists, same shape, just a different name.
#
# 3. No WordPress equivalent at all for this page type, OR a structural
#    mismatch (e.g. we send a plain string, WordPress has a repeater) —
#    dropped rather than sent, since sending garbage 400s the ENTIRE acf
#    object. These need a real remapping decision, tracked separately;
#    until then, dropping keeps publish working for everything else.
_PUBLISH_FIELD_RENAMES: dict[str, dict[str, str]] = {
    "specialization": {
        "certificate_image": "certificate_image_specialization",
        "exam_content": "examination_content",
    },
}

_PUBLISH_FIELD_DROP: dict[str, set[str]] = {
    "university": {
        "certificate_image",  # no matching field for university pages at all
        "facts",              # WP's "facts_content" is wysiwyg, not a repeater
    },
    "course": {
        "fee_plans",           # WP has flat per-tier fields, not a repeater
        "eligibility_content",  # WP's is a repeater, we send a plain string
    },
    "specialization": {
        "highlights",           # WP's "highlights_content" is wysiwyg, not a repeater
        "eligibility_content",  # WP's is a repeater, we send a plain string
    },
}

# WordPress field type is "number" (not "text") for these — a string like
# "3+" fails validation; strip to a bare int or drop if unparseable.
_PUBLISH_NUMERIC_FIELDS: dict[str, set[str]] = {
    "course": {"num_specializations"},
}


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

    # Only send keys actually registered in this page type's ACF schema.
    # A stray key here — e.g. from a [tag] left over from a different
    # page-type's docx template, or an older upload processed before an
    # extraction bug was fixed — makes WordPress reject the ENTIRE acf
    # object with a generic "Invalid parameter(s): acf" 400, since ACF's
    # REST schema validation typically forbids additional properties. Drop
    # anything unrecognized here rather than let it break the whole publish.
    valid_keys = get_valid_field_keys(page_type)
    acf_fields = {}
    dropped: list[str] = []
    for k, v in payload.items():
        if k == "_meta":
            continue
        if k in valid_keys:
            acf_fields[k] = v
        else:
            dropped.append(k)
    if dropped:
        logger.warning(
            "PUBLISH_DROPPED_UNKNOWN_FIELDS: page_type=%s keys=%s "
            "(not part of this page type's ACF schema)",
            page_type, dropped,
        )

    # hero_image has no ACF field on any page type — it's handled as the
    # native WordPress Featured Image instead (see below), never sent
    # inside "acf" at all.
    hero_image_url = acf_fields.pop("hero_image", None)

    # Drop fields with no real WordPress equivalent for this page type —
    # BEFORE image conversion below, so we never waste a download/upload
    # attempt (or error out) converting an image for a field that's about
    # to be discarded anyway.
    drop_keys = _PUBLISH_FIELD_DROP.get(page_type, set())
    still_dropped = [k for k in drop_keys if k in acf_fields]
    for k in still_dropped:
        del acf_fields[k]
    if still_dropped:
        logger.warning(
            "PUBLISH_DROPPED_UNMAPPED_FIELDS: page_type=%s keys=%s "
            "(no WordPress field for this page type, or a structural "
            "mismatch not yet reconciled)",
            page_type, still_dropped,
        )

    # Convert remaining IMAGE-type fields from a Cloudinary URL to a
    # WordPress attachment ID — a native ACF "Image" field rejects anything
    # else. Images are optional: a field with no uploaded image is left as
    # null, no download/upload attempted for it. Done BEFORE the rename
    # step below, since that operates on our internal key names.
    for key in list(acf_fields.keys()):
        if get_field_type(key, page_type) != IMAGE:
            continue
        url_value = acf_fields[key]
        if not url_value:
            acf_fields[key] = None
            continue
        try:
            acf_fields[key] = _upload_media_from_url(url_value, f"{page_type}_{key}")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to attach '{key}' image to WordPress (source: {url_value}): {exc}"
            ) from exc

    # Rename to WordPress's actual field name where it's just a naming
    # difference (same shape/type on both sides).
    for our_key, wp_key in _PUBLISH_FIELD_RENAMES.get(page_type, {}).items():
        if our_key in acf_fields:
            acf_fields[wp_key] = acf_fields.pop(our_key)

    # WordPress declares these as a "number" field — coerce "3+" -> 3,
    # drop if it doesn't parse.
    for key in _PUBLISH_NUMERIC_FIELDS.get(page_type, set()):
        if key in acf_fields and acf_fields[key] is not None:
            m = re.search(r"\d+", str(acf_fields[key]))
            acf_fields[key] = int(m.group(0)) if m else None

    # Side-load the hero image (if one was uploaded) into WordPress and
    # attach it as the post's native Featured Image, not an acf field.
    featured_media_id: int | None = None
    if hero_image_url:
        try:
            featured_media_id = _upload_media_from_url(hero_image_url, f"{page_type}_hero_image")
        except Exception as exc:
            raise RuntimeError(
                f"Failed to attach hero image to WordPress (source: {hero_image_url}): {exc}"
            ) from exc

    post_title = title or _build_title(payload, page_type, fallback=f"Untitled {page_type}")
    base_url = f"{_site_url()}/wp-json/wp/v2/{post_type}"

    if post_id:
        # Updating an already-published post: title + status + acf together
        # in one request reliably persists the acf data — confirmed
        # directly against this site (a test write to an existing post
        # round-tripped correctly).
        body: dict[str, Any] = {"title": post_title, "status": status, "acf": acf_fields}
        if featured_media_id is not None:
            body["featured_media"] = featured_media_id
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(f"{base_url}/{post_id}", json=body, auth=_auth())
        _raise_for_wp_error(resp)
        data = resp.json()
    else:
        # Creating a brand new post: sending "acf" in the SAME request that
        # creates the post silently drops the acf data on this site — the
        # post gets created (title/status persist fine) but every acf
        # field comes back empty, confirmed by directly inspecting stored
        # posts. Splitting into create-then-update (which we've confirmed
        # DOES persist acf data) works around it with no WordPress-side
        # change needed.
        create_body: dict[str, Any] = {"title": post_title, "status": status}
        if featured_media_id is not None:
            create_body["featured_media"] = featured_media_id
        with httpx.Client(timeout=_TIMEOUT) as client:
            create_resp = client.post(base_url, json=create_body, auth=_auth())
        _raise_for_wp_error(create_resp)
        new_id = create_resp.json().get("id")

        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                f"{base_url}/{new_id}", json={"acf": acf_fields}, auth=_auth()
            )
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
