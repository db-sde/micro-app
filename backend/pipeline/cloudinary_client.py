"""
Cloudinary client — image storage for ACF image fields.

Images uploaded via /upload-image go here instead of the WordPress media
library: Cloudinary returns a public, permanent HTTPS URL for the image,
which is written directly into the ACF payload (as a plain string) and
sent to WordPress under the "acf" key on publish — WordPress never needs
to host the file itself, it just renders the URL.

Auth: a single Cloudinary API environment variable. Configure via .env:

    CLOUDINARY_URL=cloudinary://<api_key>:<api_secret>@<cloud_name>

(Copy this directly from the Cloudinary console's "Product Environment
Credentials" panel — the SDK auto-parses this env var format itself, no
manual key/secret plumbing required.)

Public API
----------
is_configured()                        -> bool
upload_image(file_bytes, filename)     -> dict {url, public_id}
delete_image(public_id)                -> None
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("degreebaba.cloudinary")

_configured = False


def is_configured() -> bool:
    """True if CLOUDINARY_URL is set (or discrete cloud_name/key/secret are)."""
    if os.getenv("CLOUDINARY_URL", "").strip():
        return True
    return bool(
        os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
        and os.getenv("CLOUDINARY_API_KEY", "").strip()
        and os.getenv("CLOUDINARY_API_SECRET", "").strip()
    )


def _ensure_configured() -> None:
    """Apply explicit config once, so discrete env vars work too (not just
    CLOUDINARY_URL, which the SDK parses automatically on import)."""
    global _configured
    if _configured:
        return
    if not os.getenv("CLOUDINARY_URL", "").strip():
        cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
        api_key = os.getenv("CLOUDINARY_API_KEY", "").strip()
        api_secret = os.getenv("CLOUDINARY_API_SECRET", "").strip()
        if cloud_name and api_key and api_secret:
            cloudinary.config(
                cloud_name=cloud_name,
                api_key=api_key,
                api_secret=api_secret,
                secure=True,
            )
    _configured = True


def upload_image(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Upload an image to Cloudinary.

    Returns ``{"url": str, "public_id": str}`` — ``url`` is the permanent
    HTTPS delivery URL to store on the ACF field.
    Raises RuntimeError if Cloudinary is not configured or the call fails.
    """
    if not is_configured():
        raise RuntimeError(
            "Cloudinary is not configured (CLOUDINARY_URL, or "
            "CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / "
            "CLOUDINARY_API_SECRET, missing)."
        )
    _ensure_configured()

    # public_id without extension — Cloudinary appends the format itself.
    public_id = os.path.splitext(filename)[0]

    try:
        result = cloudinary.uploader.upload(
            file_bytes,
            public_id=public_id,
            folder="degreebaba",
            overwrite=True,
            resource_type="image",
        )
    except Exception as exc:
        raise RuntimeError(f"Cloudinary upload failed: {exc}") from exc

    url = result.get("secure_url") or result.get("url")
    logger.info("CLOUDINARY_UPLOADED: public_id=%s url=%s", result.get("public_id"), url)
    return {
        "url": url,
        "public_id": result.get("public_id"),
    }


def delete_image(public_id: str) -> None:
    """Delete an image from Cloudinary by its public_id. Best-effort."""
    if not is_configured():
        return
    _ensure_configured()
    try:
        cloudinary.uploader.destroy(public_id, resource_type="image")
        logger.info("CLOUDINARY_DELETED: public_id=%s", public_id)
    except Exception as exc:
        logger.warning("Cloudinary delete failed for %s: %s", public_id, exc)


def delete_image_by_url(url: str) -> None:
    """Delete a Cloudinary-hosted image given its delivery URL. Best-effort
    — used when an upload is deleted, to avoid leaving orphaned assets in
    the media library. Silently does nothing for a non-Cloudinary URL
    (e.g. the local-disk fallback path)."""
    if not url or "res.cloudinary.com" not in url:
        return
    # .../image/upload/v<version>/<public_id>.<ext>  ->  <public_id>
    match = re.search(r"/upload/v\d+/(.+)\.[a-zA-Z0-9]+$", url)
    if not match:
        return
    delete_image(match.group(1))
