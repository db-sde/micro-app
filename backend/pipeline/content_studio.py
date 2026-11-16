"""Hand a parsed page to Content Studio, which publishes to WordPress.

The parser no longer publishes university / course / specialization pages
itself. "Send to Content Studio" creates a draft there, straight in Senior
Review, with the original Word document attached; the senior completes the
page from it and Content Studio publishes.

The payload sent is the parser's own field names after the same content
clean-up publishing used to apply (admission steps as one list, partner
names shown once, the document's top line as the page name, …). Content
Studio translates the names into its own fields (its
server/integrations/parserImport.js).

Requests are signed like the chatbot sync: HMAC-SHA256 over
"<timestamp>.<raw body>" with CONTENT_STUDIO_IMPORT_SECRET (Content Studio's
PARSER_IMPORT_SECRET).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

import httpx

from pipeline import wordpress_client as wc

logger = logging.getLogger("degreebaba.content_studio")

PAGE_TYPES = ("university", "course", "specialization")
# A sleeping Render service takes ~90 s to wake; the import itself is quick.
_TIMEOUT = httpx.Timeout(150.0, connect=30.0)


class ContentStudioError(RuntimeError):
    """A message safe to show in the app."""


def settings() -> tuple[str, str] | None:
    url = os.getenv("CONTENT_STUDIO_URL", "").strip().rstrip("/")
    secret = os.getenv("CONTENT_STUDIO_IMPORT_SECRET", "").strip()
    return (url, secret) if url and secret else None


def prepare_payload(payload: dict[str, Any], page_type: str) -> dict[str, Any]:
    """The page's fields with the parser's content clean-up applied (what
    publishing to WordPress used to do to the content), in the parser's own
    field names. No WordPress-specific renames or lookups."""
    acf = {k: v for k, v in payload.items() if not k.startswith("_")}
    name_key, full = wc._full_page_name(payload, acf, page_type)
    if full:
        acf[name_key] = full
    acf = wc._polish_for_wordpress(acf, page_type)
    extras = wc._syllabus_extras(acf, page_type)
    extras.update(wc._placement_extras(acf, page_type))
    for key, value in extras.items():
        if not acf.get(key):
            acf[key] = value
    wc._keep_company_chips(acf, page_type)
    wc._dedupe_partner_list(acf, page_type)
    wc._dedupe_bank_list(acf, page_type)
    acf.update(wc._syllabus_years_from_content(acf, page_type))
    return acf


def review_notes(payload: dict[str, Any]) -> list[dict[str, str]]:
    """The parser's flags worth a senior's attention, plus anything the parser
    held that Content Studio doesn't take over (uploaded images, brochure)."""
    meta = payload.get("_meta") or {}
    notes = [{"field_key": f.get("field_key", ""), "message": f.get("message", "")}
             for f in meta.get("validation_flags") or []
             if isinstance(f, dict) and f.get("severity") in ("error", "warning") and f.get("message")]
    for key, label in (("hero_image", "Hero image"), ("certificate_image", "Certificate image"), ("brochure", "Brochure")):
        url = payload.get(key)
        if isinstance(url, str) and url.startswith("http"):
            notes.append({"field_key": key, "message": f"{label} uploaded in the parser: {url}"})
    return notes


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def send(upload_id: int, filename: str, page_type: str, payload: dict[str, Any], document: bytes | None,
         client: httpx.Client | None = None) -> dict[str, Any]:
    """Create the Content Studio draft. -> {draftId, status, existed, unmapped}."""
    config = settings()
    if not config:
        raise ContentStudioError("Content Studio isn't connected: set CONTENT_STUDIO_URL and CONTENT_STUDIO_IMPORT_SECRET on the server.")
    if page_type not in PAGE_TYPES:
        raise ContentStudioError("Only university, course and specialization pages go to Content Studio.")
    url, secret = config
    meta = payload.get("_meta") or {}
    body = json.dumps({
        "pageType": page_type,
        "uploadId": str(upload_id),
        "filename": filename,
        "payload": prepare_payload(payload, page_type),
        "flags": review_notes(payload),
        "relationshipHints": meta.get("relationship_hints") or {},
        "document": base64.b64encode(document).decode() if document else None,
    }, ensure_ascii=False, default=str).encode("utf-8")
    timestamp = int(time.time())
    headers = {"Content-Type": "application/json", "X-Parser-Timestamp": str(timestamp),
               "X-Parser-Signature": sign(secret, timestamp, body)}
    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT)
    try:
        resp = client.post(f"{url}/api/import/parser-draft", content=body, headers=headers)
    except httpx.HTTPError as exc:
        raise ContentStudioError(f"Couldn't reach Content Studio ({type(exc).__name__}). Try again in a minute.") from exc
    finally:
        if own:
            client.close()
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400:
        message = data.get("error") if isinstance(data, dict) else None
        if resp.status_code == 401:
            message = "Content Studio refused the request: the shared secret doesn't match (CONTENT_STUDIO_IMPORT_SECRET / PARSER_IMPORT_SECRET)."
        raise ContentStudioError(message or f"Content Studio answered HTTP {resp.status_code}.")
    logger.info("CONTENT_STUDIO_SENT: upload=%s draft=%s existed=%s", upload_id, data.get("draftId"), data.get("existed"))
    return data
