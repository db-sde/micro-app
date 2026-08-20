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

from acf.fields import get_valid_field_keys, get_field_type, get_first_sub_field_key, IMAGE, JSON_ARRAY

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


def _escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _repeater_to_html_list(items: Any, title_key: str, desc_key: str) -> str | None:
    """Reformat one of our JSON_ARRAY repeaters into a plain HTML <ul> list.

    Used for fields where WordPress's real ACF field is a wysiwyg block
    (facts_content, highlights_content), not a repeater — the repeater
    shape is still the best way to EXTRACT this content, it just needs
    reformatting into HTML on the way out to WordPress.
    """
    if not isinstance(items, list) or not items:
        return None
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = _escape_html(item.get(title_key) or "")
        desc = _escape_html(item.get(desc_key) or "")
        if title and desc:
            rows.append(f"<li><strong>{title}</strong>: {desc}</li>")
        elif title or desc:
            rows.append(f"<li>{title or desc}</li>")
    if not rows:
        return None
    return "<ul>\n" + "\n".join(rows) + "\n</ul>"


# Fee tiers WordPress models as fixed, individually-named fields (not a
# repeater) — different field names on course vs specialization. Our
# extraction stays a flexible fee_plans repeater (plan_name/plan_amount/
# plan_total); this maps recognized tier names onto WordPress's real
# fields at publish time. Tiers we can't confidently identify are simply
# left blank rather than guessed at.
_FEE_TIER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "semester": ("semester",),
    "annual": ("annual", "yearly", "per year"),
    "one_time": ("one-time", "one time", "onetime", "lump sum", "full payment", "single payment"),
}

_FEE_TIER_FIELD_MAP: dict[str, dict[str, tuple[str, str]]] = {
    "course": {
        "semester": ("semester_plan_amount", "semester_plan_amount_total"),
        "annual": ("annual_plan_amount", "annual_plan_amount_total"),
        "one_time": ("one-time_payment_amount", "one-time_payment_amount_total"),
    },
    "specialization": {
        "semester": ("semester_plan_value", "semester_plan_total"),
        "annual": ("annual_plan_value", "annual_plan_total"),
        "one_time": ("one-time_payment_value", "one-time_payment_savings"),
    },
}


def _fix_faculty_members(rows: Any) -> Any:
    """WordPress's faculty_members repeater (university) only has
    member_name/member_program/member_designation — no separate
    member_qualification sub-field (its own label is "Designation &
    Qualification", i.e. one combined field). Sending the extra
    member_qualification key 400s the whole repeater the same way
    eligibility_content did with a mismatched sub-field, so merge it into
    member_designation here rather than lose the data.
    """
    if not isinstance(rows, list):
        return rows
    fixed = []
    for row in rows:
        if not isinstance(row, dict):
            fixed.append(row)
            continue
        row = dict(row)
        qualification = row.pop("member_qualification", None)
        if qualification:
            designation = row.get("member_designation")
            row["member_designation"] = (
                f"{designation}, {qualification}" if designation else qualification
            )
        fixed.append(row)
    return fixed


def _remap_fee_plans(fee_plans: Any, page_type: str) -> dict[str, str]:
    """Best-effort map our fee_plans repeater onto WordPress's fixed,
    individually-named fee-tier fields. Matches by keyword in plan_name;
    a plan that doesn't match any known tier is left out rather than
    guessed at."""
    tier_fields = _FEE_TIER_FIELD_MAP.get(page_type)
    if not tier_fields or not isinstance(fee_plans, list):
        return {}

    out: dict[str, str] = {}
    for row in fee_plans:
        if not isinstance(row, dict):
            continue
        name_lower = str(row.get("plan_name") or "").lower()
        for tier, keywords in _FEE_TIER_KEYWORDS.items():
            if not any(kw in name_lower for kw in keywords):
                continue
            amount_key, total_key = tier_fields[tier]
            if row.get("plan_amount") and amount_key not in out:
                out[amount_key] = row["plan_amount"]
            if row.get("plan_total") and total_key not in out:
                out[total_key] = row["plan_total"]
            break
    return out


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
# (2026-07-31). Categories of mismatch between our internal schema and
# WordPress's actual registered field names:
#
# 1. hero_image doesn't exist as an ACF field on ANY of the three page
#    types — all three CPTs support "thumbnail" natively, so it's handled
#    separately below as the WordPress native Featured Image
#    (featured_media), never sent inside "acf" at all.
#
# 2. Simple renames — the field exists, same shape, just a different name.
#
# 3. Structural mismatches with a real transform (see _repeater_to_html_list
#    and _remap_fee_plans above): our facts/highlights repeaters become
#    WordPress's facts_content/highlights_content wysiwyg field via HTML
#    list formatting; eligibility_content is now extracted directly in the
#    shape WordPress's repeater expects (see acf/fields.py); fee_plans maps
#    onto WordPress's fixed per-tier fields via keyword matching.
#
# 4. No WordPress equivalent at all for this page type — dropped rather
#    than sent, since sending an unrecognized key 400s the ENTIRE acf
#    object.
_PUBLISH_FIELD_RENAMES: dict[str, dict[str, str]] = {
    "specialization": {
        "certificate_image": "certificate_image_specialization",
        "exam_content": "examination_content",
    },
}

_PUBLISH_FIELD_DROP: dict[str, set[str]] = {
    "university": {
        "certificate_image",  # no matching field for university pages at all
    },
}

# Repeater -> wysiwyg HTML-list transforms: our_key -> (wp_key, title_subkey, desc_subkey).
_PUBLISH_HTML_LIST_TRANSFORMS: dict[str, dict[str, tuple[str, str, str]]] = {
    "university": {
        "facts": ("facts_content", "fact_title", "fact_description"),
    },
    "specialization": {
        "highlights": ("highlights_content", "highlight_title", "highlight_description"),
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
        ``{"id": int, "link": str, "edit_link": str, "status": str, "warnings": list[str]}``
        — ``warnings`` lists any image field that failed to attach (network
        hiccup downloading from Cloudinary or uploading to WordPress); the
        rest of the post still published, that field is just null.
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

    # Defensive repair: a JSON_ARRAY (repeater) field should always be a
    # list of objects, but older uploads can have a plain string here —
    # e.g. the KV fast-path used to write "accreditations" as one flat
    # string ("NAAC A+, UGC, AICTE") before that was fixed at the source.
    # WordPress's ACF schema rejects a string where a repeater is expected
    # ("acf[accreditations][0] is not of type object"), 400ing the whole
    # publish — wrap it into a single-row repeater instead of failing.
    for key, value in list(acf_fields.items()):
        if get_field_type(key, page_type) != JSON_ARRAY:
            continue
        if isinstance(value, str) and value.strip():
            sub_key = get_first_sub_field_key(key, page_type) or "value"
            acf_fields[key] = [{sub_key: value.strip()}]
            logger.warning(
                "PUBLISH_COERCED_STRING_TO_REPEATER: page_type=%s field=%s",
                page_type, key,
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
    #
    # This is a network call (download from Cloudinary, upload to
    # WordPress) — a transient hiccup here must not take down the rest of
    # the publish. Previously any failure raised and aborted the whole
    # request, so e.g. certificate_image flaking out would also take
    # certificate_description and everything else with it, even though
    # they have nothing to do with the failure. Log a warning and leave
    # that one field null instead.
    image_warnings: list[str] = []
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
            logger.warning(
                "PUBLISH_IMAGE_ATTACH_FAILED: page_type=%s field=%s source=%s error=%s",
                page_type, key, url_value, exc,
            )
            acf_fields[key] = None
            image_warnings.append(f"Could not attach '{key}': {exc}")

    # Rename to WordPress's actual field name where it's just a naming
    # difference (same shape/type on both sides).
    for our_key, wp_key in _PUBLISH_FIELD_RENAMES.get(page_type, {}).items():
        if our_key in acf_fields:
            acf_fields[wp_key] = acf_fields.pop(our_key)

    # Reformat repeater fields whose real WordPress field is a wysiwyg
    # HTML block, not a repeater (facts_content, highlights_content).
    for our_key, (wp_key, title_key, desc_key) in _PUBLISH_HTML_LIST_TRANSFORMS.get(page_type, {}).items():
        if our_key not in acf_fields:
            continue
        html = _repeater_to_html_list(acf_fields.pop(our_key), title_key, desc_key)
        if html:
            acf_fields[wp_key] = html

    # Map our flexible fee_plans repeater onto WordPress's fixed,
    # individually-named fee-tier fields (see _remap_fee_plans).
    if "fee_plans" in acf_fields:
        fee_plans = acf_fields.pop("fee_plans")
        acf_fields.update(_remap_fee_plans(fee_plans, page_type))

    if page_type == "university" and "faculty_members" in acf_fields:
        acf_fields["faculty_members"] = _fix_faculty_members(acf_fields["faculty_members"])

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
            logger.warning(
                "PUBLISH_IMAGE_ATTACH_FAILED: page_type=%s field=hero_image source=%s error=%s",
                page_type, hero_image_url, exc,
            )
            image_warnings.append(f"Could not attach hero image: {exc}")

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
        "warnings": image_warnings,
    }
    logger.info(
        "WP_PUBLISHED: page_type=%s post_type=%s id=%s status=%s warnings=%s",
        page_type, post_type, wp_id, result["status"], len(image_warnings),
    )
    return result
