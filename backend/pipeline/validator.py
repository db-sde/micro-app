"""
Payload validator — checks extracted payload against required fields and
computes a quality score.

Returns a validation report with:
  - summary: total_required, mapped, thin, missing, quality_score
  - field_report: per-field status list
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from acf.fields import ACF_FIELDS, SKIP_EXTRACTION_FIELDS, get_field_type

SHORT_OK_FIELDS = {
    'university_name', 'university_full_name', 'established_year',
    'naac_grade', 'ugc_approved', 'ugc_status', 'mode_of_learning', 'mode',
    'starting_fee', 'total_fee', 'num_programs', 'num_specializations',
    'duration', 'validity', 'emi_amount', 'admission_fee_note', 'course_amount_range',
    'programs_intro', 'specializations_intro', 'eligibility_summary',
    'certificate_description', 'faculty_intro',
    'seo_title', 'meta_description', 'hero_description',
    # All heading fields
    'about_heading', 'why_choose_heading', 'facts_heading', 'accreditations_heading',
    'programs_heading', 'admission_heading', 'emi_heading', 'exam_heading',
    'faculty_heading', 'placement_heading', 'reviews_heading', 'faqs_heading',
    'highlights_heading', 'specializations_heading', 'fee_heading',
    'eligibility_heading', 'syllabus_heading', 'placement_heading',
    'jobs_heading', 'certificate_heading', 'other_specs_heading',
}

def get_field_status(field_key: str, value: Any, field_type: str, word_count: int) -> str:
    if field_key in SKIP_EXTRACTION_FIELDS:
        return 'skipped'    # not missing — just not extractable from Word
    if value is None or value == '' or value == [] or value == {}:
        return 'missing'
    if field_type in ('html', 'textarea', 'text') and word_count < 30:
        if field_key not in SHORT_OK_FIELDS:
            return 'thin'
    return 'mapped'

def value_fingerprint(value: Any) -> str:
    """Short stable hash of a field value, so a stored flag can tell whether
    the value it was raised on has since been edited."""
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def stored_flags(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Flags saved by extraction v2 in payload._meta, minus those whose field
    has been edited since. None for payloads without stored flags (v1)."""
    meta = payload.get("_meta") if isinstance(payload, dict) else None
    flags = (meta or {}).get("validation_flags")
    if not isinstance(flags, list):
        return None
    return [
        f for f in flags
        if isinstance(f, dict) and f.get("field_key")
        and ("value_fp" not in f or f["value_fp"] == value_fingerprint(payload.get(f["field_key"])))
    ]


def validate_payload(
    payload: dict[str, Any],
    page_type: str,
    flags: list[dict[str, Any]] | None = None,
    extra_fields: list[str] | None = None,
) -> dict[str, Any]:
    """Validate the extracted payload and return a quality report.

    ``flags`` / ``extra_fields`` are used by extraction v2 only: each
    field_report entry then gets its own ``flags`` list, the summary gets
    a ``flagged`` count (fields with an error or warning), and the extra
    fields (v2-only WordPress fields) are reported too. A v2 payload
    carries both in ``_meta``, so every endpoint that re-validates keeps
    showing them; a flag disappears once its field is edited. Without
    either, the report is exactly what it always was.
    """
    if flags is None:
        flags = stored_flags(payload)
    if extra_fields is None and flags is not None:
        extra_fields = ((payload.get("_meta") or {}).get("extra_fields")) or []
    fields_list = ACF_FIELDS.get(page_type, [])
    # We validate all fields listed in ACF_FIELDS for this page_type
    required_fields = [f['key'] for f in fields_list]
    required_fields += [k for k in (extra_fields or []) if k not in required_fields]
    total_required = len(required_fields)

    mapped = 0
    thin = 0
    missing = 0
    skipped = 0
    field_report: list[dict[str, Any]] = []

    for field_key in required_fields:
        value = payload.get(field_key)
        ft = get_field_type(field_key, page_type)
        
        word_count = 0
        if value:
            word_count = len(str(value).split())

        status = get_field_status(field_key, value, ft, word_count)

        if status == 'missing':
            missing += 1
        elif status == 'thin':
            thin += 1
        elif status == 'skipped':
            skipped += 1
        else:
            mapped += 1

        field_report.append(
            {
                "field_key": field_key,
                "status": status,
                "has_value": value is not None and field_key in payload,
                "value_preview": _preview(value),
            }
        )

    # Quality score: mapped counts 1.0, thin counts 0.5, missing counts 0
    # Skipped fields should NOT lower the quality score. They are just ignored in denominator.
    quality_score = 0.0
    effective_total = total_required - skipped
    if effective_total > 0:
        quality_score = round(
            (mapped * 1.0 + thin * 0.5) / effective_total * 100, 2
        )

    summary = {
        "total_required": total_required,
        "mapped": mapped,
        "thin": thin,
        "missing": missing,
        "quality_score": quality_score,
    }
    if flags is not None:
        by_field: dict[str, list[dict[str, Any]]] = {}
        for f in flags:
            by_field.setdefault(f["field_key"], []).append(f)
        for entry in field_report:
            entry["flags"] = by_field.get(entry["field_key"], [])
        summary["flagged"] = sum(
            1 for entry in field_report
            if any(f.get("severity") in ("error", "warning") for f in entry["flags"])
        )
    return {"summary": summary, "field_report": field_report}


# ────────────────────────── helpers ──────────────────────────


def _preview(value: Any, max_len: int = 120) -> str | None:
    """Return a short preview string of a value for the report."""
    if value is None:
        return None
    if isinstance(value, str):
        return value[:max_len] + ("…" if len(value) > max_len else "")
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if isinstance(value, dict):
        inner = value.get("value")
        if inner is not None:
            return _preview(inner, max_len)
        return f"{{dict with {len(value)} keys}}"
    return str(value)[:max_len]
