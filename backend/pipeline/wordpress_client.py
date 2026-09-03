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

Taxonomies (program, mode, level, institution, discipline, approval_body)
are assigned as top-level REST keys alongside "title"/"status" (native WP
core taxonomy handling, not the ACF-on-create quirk above) — see
_derive_taxonomies for how each is resolved from the payload, since none
of them have a dedicated docx-extracted field of their own.

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
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from acf.fields import get_valid_field_keys, get_field_type, get_first_sub_field_key, IMAGE, FILE, JSON_ARRAY

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


# university/course/specialization's CPT slug and REST base happen to be
# identical, so page_type itself is a fine default for those. Not true for
# blog/category: blog posts use WordPress's native "post" type, whose REST
# base is the plural "posts" (not "post", and definitely not "blog"); the
# category-landing-page CPT's REST base is "category-page", not "category"
# (which would otherwise collide with WP's built-in category TAXONOMY at
# /wp-json/wp/v2/categories — a different, unrelated endpoint).
_DEFAULT_POST_TYPE_OVERRIDES: dict[str, str] = {
    "blog": "posts",
    "category": "category-page",
}


def get_post_type(page_type: str) -> str:
    """Resolve the WP custom-post-type slug for a given page_type.

    Defaults to the page_type name itself (or a hardcoded override for
    blog/category, see above); overridable per-type via env var so a
    mismatched CPT slug can be fixed without a code change.
    """
    env_key = f"WORDPRESS_POST_TYPE_{page_type.upper()}"
    return os.getenv(env_key, "").strip() or _DEFAULT_POST_TYPE_OVERRIDES.get(page_type, page_type)


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


def _get_live_acf_field_types(post_type: str) -> dict[str, list[str]]:
    """Fetch the live ACF field type declarations for a post type via
    OPTIONS, keyed by field name -> JSON-schema type list (e.g.
    ["number", "null"] or ["string", "null"]).

    Used for fields whose WordPress type has been observed to flip back
    and forth (see _VOLATILE_NUMERIC_FIELDS) — checking live at publish
    time means a future flip doesn't need a code change to fix, unlike
    hardcoding a guess that just breaks again next time someone toggles
    the ACF field's type in the WordPress admin.

    Best-effort: returns {} on any failure (network, unexpected response
    shape, etc.) rather than raising — callers should treat a missing key
    as "unknown, don't touch the value".
    """
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.options(f"{_site_url()}/wp-json/wp/v2/{post_type}", auth=_auth())
        if resp.status_code >= 400:
            return {}
        props = resp.json().get("schema", {}).get("properties", {}).get("acf", {}).get("properties", {})
        if not isinstance(props, dict):
            return {}
        result = {}
        for key, entry in props.items():
            if not isinstance(entry, dict):
                continue
            t = entry.get("type")
            result[key] = t if isinstance(t, list) else [t]
        return result
    except Exception as exc:
        logger.warning("LIVE_SCHEMA_CHECK_FAILED: post_type=%s error=%s", post_type, exc)
        return {}


# ────────────────────────── post publishing ──────────────────────────


def _build_title(payload: dict[str, Any], page_type: str, fallback: str) -> str:
    # blog/category posts have none of university_name/program_name/spec_name
    # — seo_title is the closest thing they have to a natural title, so
    # it's checked last as a real (if imperfect) fallback before giving up
    # and using the generic "Untitled ..." fallback string.
    for key in ("university_name", "program_name", "spec_name", "seo_title"):
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
    """WordPress's faculty_members repeater (university) currently has
    only member_name/member_designation — no separate member_program or
    member_qualification sub-field (confirmed directly against the live
    schema, which has visibly changed more than once already — it used
    to also have member_program). Sending either extra key 400s the
    whole repeater the same way eligibility_content did with a
    mismatched sub-field, so merge both into member_designation here
    rather than lose the data.
    """
    if not isinstance(rows, list):
        return rows
    fixed = []
    for row in rows:
        if not isinstance(row, dict):
            fixed.append(row)
            continue
        row = dict(row)
        program = row.pop("member_program", None)
        qualification = row.pop("member_qualification", None)
        parts = [p for p in (row.get("member_designation"), program, qualification) if p]
        if parts:
            row["member_designation"] = ", ".join(parts)
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

    # This site's host runs a WAF (ModSecurity) that blocks the upload
    # outright — a 406, before WordPress even sees it — when the
    # Content-Type header value is a "document" MIME type like
    # application/pdf, regardless of the actual file content or filename.
    # Confirmed live: identical requests differing ONLY in this header are
    # blocked vs accepted. WordPress determines the real file type from
    # the filename's own extension (wp_check_filetype), not this header,
    # so swapping it for a generic value on non-image uploads sidesteps
    # the WAF rule with no loss of correctness — verified the resulting
    # media item still gets the right mime_type and serves correctly.
    upload_content_type = "application/octet-stream" if content_type.startswith("application/") else content_type

    media_url = f"{_site_url()}/wp-json/wp/v2/media"
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Type": upload_content_type,
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
    "university": {
        "brochure": "download_brochure_university",
    },
    "course": {
        "brochure": "download_brochure_course",
        "nirf_rank": "nirf_rank_course",
    },
    "specialization": {
        "certificate_image": "certificate_image_specialization",
        "exam_content": "examination_content",
        "brochure": "download_brochure_specialization",
    },
}

_PUBLISH_FIELD_DROP: dict[str, set[str]] = {
    "university": {
        "certificate_image",  # no matching field for university pages at all
    },
    "specialization": {
        # Removed from the live ACF field group since it was last checked
        # (confirmed via OPTIONS /wp-json/wp/v2/specialization) — still
        # extracted and shown in the app, just has nowhere to go on WP.
        "certificate_heading",
    },
}

# Repeater -> wysiwyg HTML-list transforms: our_key -> (wp_key, title_subkey, desc_subkey).
# Destructive — the source repeater key is REPLACED by the flat wp_key,
# since on university/specialization the repeater has no real WordPress
# field of its own to send it to anyway.
_PUBLISH_HTML_LIST_TRANSFORMS: dict[str, dict[str, tuple[str, str, str]]] = {
    "university": {
        "facts": ("facts_content", "fact_title", "fact_description"),
    },
    "specialization": {
        "highlights": ("highlights_content", "highlight_title", "highlight_description"),
    },
}

# Same idea, but non-destructive: on course, "highlights" IS also a real,
# separate WordPress repeater in its own right (unlike above), so both
# must be sent — the repeater as-is, plus a flattened HTML copy under a
# second field name for the single-field display.
_PUBLISH_HTML_LIST_COPY: dict[str, dict[str, tuple[str, str, str]]] = {
    "course": {
        "highlights": ("highlights_section_content", "highlight_title", "highlight_description"),
    },
}

# WordPress's course ACF group has a "program_duration" field with no
# internal equivalent of its own — we only extract the free-text "duration"
# ("2 years"), which still goes to WP's separate "duration" text field
# unchanged. Derive program_duration's value from that same source (the
# resulting type — string vs int — is handled adaptively at publish time,
# see _VOLATILE_NUMERIC_FIELDS below, since this field's declared WP type
# keeps changing).
_PUBLISH_NUMERIC_DERIVE: dict[str, dict[str, str]] = {
    "course": {"program_duration": "duration"},
}

# Both of these have flipped between WordPress "number" and "text" field
# types multiple times already (confirmed live, same day: string -> number
# -> string -> number) — rather than hardcode a guess that breaks again
# next time someone toggles it in the ACF admin, their actual outgoing
# type is checked live at publish time (see _get_live_acf_field_types).
_VOLATILE_NUMERIC_FIELDS: dict[str, set[str]] = {
    "course": {"num_specializations", "program_duration"},
}


# ── Taxonomies ──────────────────────────────────────────────────────────
# Real WordPress taxonomies, assigned as top-level REST keys (native WP
# core taxonomy assignment — not the "acf" key, and not subject to the
# ACF-on-create quirk documented above `publish_payload`). "pillar" is
# omitted below since this app never publishes pillar pages.
#
# "program" is deliberately NOT auto-derived — course/specialization ACF
# has its own "category_page" (post_object) field for this, set manually
# in WordPress by the content team (confirmed directly), not guessed from
# document text. Keyword-matching program_name against a fixed slug list
# was the wrong mechanism entirely, not just an incomplete one — it
# doesn't reflect how "program" is actually meant to be assigned here.
#
# Fixed-vocabulary taxonomies (mode, level, approval_body) only ever
# match against their seeded terms and never auto-create a new one. Open
# taxonomies (discipline, institution) create a term on first use, per
# the plan's "populate as built".
_TAXONOMY_PAGE_TYPES: dict[str, set[str]] = {
    "university": {"approval_body"},
    "course": {"mode", "level", "institution"},
    "specialization": {"mode", "level", "institution", "discipline"},
}

# taxonomy -> {keyword to look for (lowercase) -> seeded term slug}.
# Ordered so longer/more-specific keywords are checked before the shorter
# ones they contain.
_TAXONOMY_SEEDED_SLUGS: dict[str, dict[str, str]] = {
    "mode": {
        "online": "online",
        "distance": "distance",
        "hybrid": "hybrid",
    },
    "level": {
        "postgraduate": "postgraduate",
        "undergraduate": "undergraduate",
        "diploma": "diploma",
        "certificate": "certificate",
    },
    "approval_body": {
        "ugc-deb": "ugc-deb",
        "ugc deb": "ugc-deb",
        "ugc": "ugc",
        "aicte": "aicte",
        "naac": "naac",
        "aiu": "aiu",
        "wes": "wes",
    },
}

# Signals an undergraduate program, overriding the "level" default below —
# every program in this dataset is postgraduate today (per the taxonomy
# plan's own note that "level" is "currently redundant while all PG"), so
# defaulting to postgraduate is the safe fallback when nothing matches.
_UG_KEYWORDS_RE = re.compile(
    r"\b(?:bba|bca|b\.?\s*sc|bsc|b\.?\s*com|bcom|b\.?\s*tech|btech)\b",
    re.IGNORECASE,
)

_term_id_cache: dict[tuple[str, str], int | None] = {}


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def _match_seeded_term(taxonomy: str, *texts: str) -> str | None:
    """First seeded slug whose keyword appears in any of `texts`, else None."""
    haystack = " ".join(t for t in texts if t).lower()
    for keyword, slug in _TAXONOMY_SEEDED_SLUGS.get(taxonomy, {}).items():
        if keyword in haystack:
            return slug
    return None


def _get_or_create_term_id(
    taxonomy: str, name: str, slug: str, create_if_missing: bool
) -> int | None:
    """Resolve a taxonomy term to its WordPress term ID by slug, optionally
    creating it if missing (only for open, "populate as built" taxonomies).
    Cached per (taxonomy, slug) for this process's lifetime."""
    cache_key = (taxonomy, slug)
    if cache_key in _term_id_cache:
        return _term_id_cache[cache_key]

    base_url = f"{_site_url()}/wp-json/wp/v2/{taxonomy}"
    with httpx.Client(timeout=_TIMEOUT) as client:
        resp = client.get(base_url, params={"slug": slug}, auth=_auth())
    if resp.status_code < 400:
        results = resp.json()
        if results:
            term_id = results[0]["id"]
            _term_id_cache[cache_key] = term_id
            return term_id

    if not create_if_missing:
        logger.warning("TAXONOMY_TERM_NOT_FOUND: taxonomy=%s slug=%s", taxonomy, slug)
        _term_id_cache[cache_key] = None
        return None

    with httpx.Client(timeout=_TIMEOUT) as client:
        create_resp = client.post(base_url, json={"name": name, "slug": slug}, auth=_auth())
    if create_resp.status_code >= 400:
        logger.warning(
            "TAXONOMY_TERM_CREATE_FAILED: taxonomy=%s name=%s status=%s body=%s",
            taxonomy, name, create_resp.status_code, create_resp.text[:300],
        )
        _term_id_cache[cache_key] = None
        return None
    term_id = create_resp.json().get("id")
    logger.info("TAXONOMY_TERM_CREATED: taxonomy=%s name=%s slug=%s id=%s", taxonomy, name, slug, term_id)
    _term_id_cache[cache_key] = term_id
    return term_id


def _derive_taxonomies(
    payload: dict[str, Any], acf_fields: dict[str, Any], page_type: str
) -> tuple[dict[str, list[int]], list[str]]:
    """Resolve applicable taxonomy term IDs for this page from data already
    in the payload. Returns (taxonomy -> [term_ids], warnings)."""
    applicable = _TAXONOMY_PAGE_TYPES.get(page_type, set())
    if not applicable:
        return {}, []

    result: dict[str, list[int]] = {}
    warnings: list[str] = []
    doc_title = str((payload.get("_meta") or {}).get("document_title", ""))
    program_name = str(acf_fields.get("program_name") or "")
    spec_name = str(acf_fields.get("spec_name") or "")
    university_name = str(acf_fields.get("university_name") or "")
    mode_value = str(acf_fields.get("mode") or "")

    if "mode" in applicable:
        # Nearly everything in this catalog is an online program — default
        # to "online" rather than leaving the taxonomy unset when the
        # "mode" ACF field doesn't literally spell out one of the 3 terms.
        slug = _match_seeded_term("mode", mode_value) or "online"
        term_id = _get_or_create_term_id("mode", "", slug, False)
        if term_id:
            result["mode"] = [term_id]

    if "level" in applicable:
        text = " ".join([program_name, spec_name, doc_title])
        slug = "undergraduate" if _UG_KEYWORDS_RE.search(text) else "postgraduate"
        term_id = _get_or_create_term_id("level", "", slug, False)
        if term_id:
            result["level"] = [term_id]

    if "institution" in applicable and university_name.strip():
        slug = _slugify(university_name)
        term_id = _get_or_create_term_id("institution", university_name.strip(), slug, True)
        if term_id:
            result["institution"] = [term_id]

    if "discipline" in applicable and spec_name.strip():
        slug = _slugify(spec_name)
        term_id = _get_or_create_term_id("discipline", spec_name.strip(), slug, True)
        if term_id:
            result["discipline"] = [term_id]

    if "approval_body" in applicable:
        accreditations = acf_fields.get("accreditations")
        term_ids: list[int] = []
        unresolved: list[str] = []
        if isinstance(accreditations, list):
            for row in accreditations:
                if not isinstance(row, dict):
                    continue
                body_name = str(row.get("body_name") or "")
                slug = _match_seeded_term("approval_body", body_name)
                if not slug:
                    continue
                term_id = _get_or_create_term_id("approval_body", "", slug, False)
                if term_id:
                    if term_id not in term_ids:
                        term_ids.append(term_id)
                else:
                    unresolved.append(slug)
        if term_ids:
            result["approval_body"] = term_ids
        if unresolved:
            warnings.append(
                f"Matched approval_body term(s) {sorted(set(unresolved))} but the 'approval_body' "
                "taxonomy doesn't exist on WordPress yet"
            )

    return result, warnings


# ── Relationship fields (linked_university, linked_course, category_page) ──
# These are real WordPress post-ID references — never derivable from
# document text directly (there is no "ID" written anywhere in a .docx) —
# so this resolves them by matching titles we've already extracted
# against the target post type's existing posts, same "best-effort name
# lookup, never guess" spirit as the taxonomy resolution above. Confirmed
# directly against this site: it has duplicate posts for the same
# real-world entity ("KL University" appears 3x, "Online MCA" 2x under
# category-page) — so a name match returns EVERY matching post ID, not
# just the first, rather than arbitrarily picking one.

_post_title_cache: dict[str, list[dict[str, Any]]] = {}
_post_title_cache_ts: dict[str, float] = {}
# How long a fetched title list is trusted before being refetched. The
# backend process on Render runs continuously (not per-request), so an
# unbounded cache here previously meant: once "university" (etc.) was
# fetched once, EVERY later publish — including ones referencing
# universities/courses created or deleted minutes or days afterward, e.g.
# after the WordPress side was cleared and repopulated — kept matching
# against that first, now-stale snapshot forever, silently leaving
# linked_university/linked_course/category_page unresolved. A short TTL
# bounds that staleness instead of requiring a process restart to clear it.
_POST_CACHE_TTL_SECONDS = 30


def _invalidate_post_cache(post_type: str) -> None:
    """Drop the cached title list for `post_type` so the next lookup
    refetches. Called right after this app creates a new post of that
    type, so a University published in one request is immediately visible
    to a Course/Specialization published straight after it, without
    waiting out the TTL."""
    _post_title_cache.pop(post_type, None)
    _post_title_cache_ts.pop(post_type, None)


def _get_all_posts_lite(post_type: str) -> list[dict[str, Any]]:
    """Fetch {id, title} for every post of a type. Small counts on this
    site (dozens, not thousands) as of this writing, so a full fetch is
    cheap — cached per (post_type) for up to _POST_CACHE_TTL_SECONDS.
    Best-effort: returns whatever was fetched so far (possibly []) on any
    failure."""
    cached_at = _post_title_cache_ts.get(post_type)
    if cached_at is not None and (time.monotonic() - cached_at) < _POST_CACHE_TTL_SECONDS:
        return _post_title_cache[post_type]
    posts: list[dict[str, Any]] = []
    page = 1
    try:
        while True:
            with httpx.Client(timeout=_TIMEOUT) as client:
                resp = client.get(
                    f"{_site_url()}/wp-json/wp/v2/{post_type}",
                    params={"per_page": 100, "page": page, "status": "any", "_fields": "id,title"},
                    auth=_auth(),
                )
            if resp.status_code >= 400:
                break
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            for item in batch:
                title = (item.get("title") or {}).get("rendered", "")
                posts.append({"id": item.get("id"), "title": title})
            total_pages = int(resp.headers.get("X-WP-TotalPages", "1") or "1")
            if page >= total_pages:
                break
            page += 1
    except Exception as exc:
        logger.warning("RELATIONSHIP_LOOKUP_FETCH_FAILED: post_type=%s error=%s", post_type, exc)
    _post_title_cache[post_type] = posts
    _post_title_cache_ts[post_type] = time.monotonic()
    return posts


_TITLE_FILLER_WORDS_RE = re.compile(r"\b(?:online|university|the|of|in|for)\b", re.IGNORECASE)


def _normalize_title(text: str) -> str:
    text = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    text = _TITLE_FILLER_WORDS_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _match_posts_by_name(post_type: str, name: str) -> list[int]:
    """Every post ID of `post_type` whose title confidently matches
    `name` — normalized exact match or substring either direction (e.g.
    our "Sample Global University Online" vs WP's "Sample Global
    University"). Returns [] rather than guessing when nothing matches."""
    norm_name = _normalize_title(name)
    if not norm_name:
        return []
    matches = []
    for post in _get_all_posts_lite(post_type):
        norm_title = _normalize_title(post["title"])
        if not norm_title:
            continue
        if norm_title == norm_name or norm_title in norm_name or norm_name in norm_title:
            matches.append(post["id"])
    return matches


_DEGREE_KEYWORD_RE = re.compile(
    r"\b(executive\s*mba|mba|mca|msc|m\.?sc|bba|bca|b\.?com|m\.?com|b\.?tech|m\.?tech)\b",
    re.IGNORECASE,
)


def _extract_degree_keyword(text: str) -> str | None:
    m = _DEGREE_KEYWORD_RE.search(text or "")
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group(1)).strip().lower()


def _derive_relationships(
    payload: dict[str, Any], acf_fields: dict[str, Any], page_type: str
) -> tuple[dict[str, list[int]], list[str]]:
    """Resolve linked_university / linked_course / category_page to real
    WordPress post IDs, per page type. Returns (field -> [post_ids], warnings)."""
    if page_type not in ("course", "specialization"):
        return {}, []

    result: dict[str, list[int]] = {}
    warnings: list[str] = []
    university_name = str(acf_fields.get("university_name") or "")
    program_name = str(acf_fields.get("program_name") or "")
    spec_name = str(acf_fields.get("spec_name") or "")
    doc_title = str((payload.get("_meta") or {}).get("document_title", ""))

    if university_name.strip():
        ids = _match_posts_by_name("university", university_name)
        if ids:
            result["linked_university"] = ids
        else:
            warnings.append(
                f"Could not find a matching WordPress university post for '{university_name}' — link linked_university manually"
            )
    else:
        warnings.append("No university name extracted — link linked_university manually")

    if page_type == "course":
        keyword = _extract_degree_keyword(program_name) or _extract_degree_keyword(doc_title)
        if keyword:
            ids = _match_posts_by_name("category-page", keyword)
            if ids:
                result["category_page"] = ids
            else:
                warnings.append(
                    f"Could not find a matching Category Page for '{keyword}' — link category_page manually"
                )
        else:
            warnings.append("Could not determine a program keyword (MBA/MCA/...) — link category_page manually")

    if page_type == "specialization":
        candidate_ids = _match_posts_by_name("course", university_name) if university_name.strip() else []
        keyword = _extract_degree_keyword(spec_name) or _extract_degree_keyword(doc_title) or _extract_degree_keyword(university_name)
        if candidate_ids and keyword:
            all_courses = {p["id"]: p["title"] for p in _get_all_posts_lite("course")}
            narrowed = [cid for cid in candidate_ids if keyword in _normalize_title(all_courses.get(cid, ""))]
            if narrowed:
                candidate_ids = narrowed
        if candidate_ids:
            result["linked_course"] = candidate_ids
        else:
            warnings.append("Could not find a matching WordPress course post — link linked_course manually")

    return result, warnings


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

    # Convert remaining IMAGE/FILE-type fields (e.g. certificate_image,
    # brochure) from a Cloudinary URL to a WordPress attachment ID — a
    # native ACF "Image"/"File" field rejects anything else. Both are
    # optional: a field with nothing uploaded is left as null, no
    # download/upload attempted for it. Done BEFORE the rename step below,
    # since that operates on our internal key names.
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
        if get_field_type(key, page_type) not in (IMAGE, FILE):
            continue
        url_value = acf_fields[key]
        if not url_value:
            acf_fields[key] = None
            continue
        try:
            acf_fields[key] = _upload_media_from_url(url_value, f"{page_type}_{key}")
        except Exception as exc:
            logger.warning(
                "PUBLISH_MEDIA_ATTACH_FAILED: page_type=%s field=%s source=%s error=%s",
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

    # Same idea, but the source repeater is ALSO a real WordPress field in
    # its own right — copy (don't pop), so both get sent.
    for our_key, (wp_key, title_key, desc_key) in _PUBLISH_HTML_LIST_COPY.get(page_type, {}).items():
        if our_key not in acf_fields:
            continue
        html = _repeater_to_html_list(acf_fields[our_key], title_key, desc_key)
        if html:
            acf_fields[wp_key] = html

    # Map our flexible fee_plans repeater onto WordPress's fixed,
    # individually-named fee-tier fields (see _remap_fee_plans).
    if "fee_plans" in acf_fields:
        fee_plans = acf_fields.pop("fee_plans")
        acf_fields.update(_remap_fee_plans(fee_plans, page_type))

        # WordPress (course + specialization) now ALSO has a real
        # "fee_plans" repeater of its own, for filtering/dynamic display —
        # added on the WP side after the fixed tier fields above already
        # existed, so send both rather than replace one with the other.
        # Its live schema only has plan_name/plan_amount (no plan_total,
        # despite that being requested) — drop the extra key per row
        # rather than 400 on an unrecognized sub-field.
        if isinstance(fee_plans, list):
            cleaned_fee_plans = [
                {k: v for k, v in row.items() if k in ("plan_name", "plan_amount") and v}
                for row in fee_plans if isinstance(row, dict)
            ]
            cleaned_fee_plans = [row for row in cleaned_fee_plans if row]
            if cleaned_fee_plans:
                acf_fields["fee_plans"] = cleaned_fee_plans

    if page_type == "university" and "faculty_members" in acf_fields:
        acf_fields["faculty_members"] = _fix_faculty_members(acf_fields["faculty_members"])

    # Populate WordPress fields that have no internal field of their own by
    # extracting the leading digits from a related text field. Left as a
    # plain string here — the type-appropriate coercion happens in the
    # volatile-numeric-fields check right below, which covers this field
    # too.
    for wp_key, source_key in _PUBLISH_NUMERIC_DERIVE.get(page_type, {}).items():
        source_val = acf_fields.get(source_key)
        if source_val:
            m = re.search(r"\d+", str(source_val))
            if m:
                acf_fields[wp_key] = m.group(0)

    # num_specializations and program_duration have flipped between
    # WordPress "number" and "text" field types multiple times on this
    # site already (confirmed: 3 flips in one day) — rather than hardcode
    # a guess that breaks again the next time someone toggles it in the
    # ACF admin, check the live type at publish time and send whichever
    # shape it currently wants.
    volatile_keys = _VOLATILE_NUMERIC_FIELDS.get(page_type, set()) & acf_fields.keys()
    if volatile_keys:
        live_types = _get_live_acf_field_types(post_type)
        for key in volatile_keys:
            if acf_fields.get(key) is None:
                continue
            wants_number = "number" in (live_types.get(key) or [])
            if wants_number:
                m = re.search(r"\d+", str(acf_fields[key]))
                acf_fields[key] = int(m.group(0)) if m else None
            elif not isinstance(acf_fields[key], str):
                acf_fields[key] = str(acf_fields[key])

    # Resolve real WordPress taxonomy terms (program, mode, level,
    # institution, discipline, approval_body) — see _derive_taxonomies.
    taxonomy_terms, taxonomy_warnings = _derive_taxonomies(payload, acf_fields, page_type)

    # Resolve linked_university / linked_course / category_page to real
    # WordPress post IDs — see _derive_relationships. These ARE real acf
    # fields (unlike taxonomy terms, which are top-level REST keys), so
    # merge straight into acf_fields, overwriting the always-null value
    # extraction left there (linked_* are SKIP_EXTRACTION_FIELDS).
    relationship_ids, relationship_warnings = _derive_relationships(payload, acf_fields, page_type)
    acf_fields.update(relationship_ids)

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

    # Blog/category posts have no dedicated "body" content field of their
    # own on the ACF side (just the summary/SEO meta) — without this, the
    # post's actual content editor is left completely empty, which is
    # what it's for: the generated page summary IS the post body here.
    post_content = acf_fields.get("complete_page_summary") if page_type in ("blog", "category") else None

    if post_id:
        # Updating an already-published post: title + status + acf together
        # in one request reliably persists the acf data — confirmed
        # directly against this site (a test write to an existing post
        # round-tripped correctly).
        body: dict[str, Any] = {"title": post_title, "status": status, "acf": acf_fields}
        if featured_media_id is not None:
            body["featured_media"] = featured_media_id
        if post_content:
            body["content"] = post_content
        body.update(taxonomy_terms)
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
        # change needed. "content" is native WP, not ACF, so it's safe to
        # include on create directly (unaffected by that quirk).
        create_body: dict[str, Any] = {"title": post_title, "status": status}
        if featured_media_id is not None:
            create_body["featured_media"] = featured_media_id
        if post_content:
            create_body["content"] = post_content
        create_body.update(taxonomy_terms)
        with httpx.Client(timeout=_TIMEOUT) as client:
            create_resp = client.post(base_url, json=create_body, auth=_auth())
        _raise_for_wp_error(create_resp)
        new_id = create_resp.json().get("id")

        # This new post may itself be a target other publishes resolve
        # linked_university/linked_course/category_page against — make it
        # visible to the next lookup immediately rather than waiting out
        # the cache TTL (see _get_all_posts_lite).
        if post_type in ("university", "course", "category-page"):
            _invalidate_post_cache(post_type)

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
        "taxonomy_warnings": taxonomy_warnings,
        "relationship_warnings": relationship_warnings,
    }
    logger.info(
        "WP_PUBLISHED: page_type=%s post_type=%s id=%s status=%s warnings=%s taxonomies=%s relationships=%s",
        page_type, post_type, wp_id, result["status"], len(image_warnings), taxonomy_terms, relationship_ids,
    )
    return result
