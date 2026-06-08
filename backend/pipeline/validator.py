"""
Payload validator — checks extracted payload against required fields and
computes a quality score.

Returns a validation report with:
  - summary: total_required, mapped, thin, missing, quality_score
  - field_report: per-field status list
"""

from __future__ import annotations

import json
from typing import Any

from acf.fields import ACF_FIELDS, SKIP_EXTRACTION_FIELDS, get_field_type

SHORT_OK_FIELDS = {
    'university_name', 'university_full_name', 'established_year', 'cdoe_year',
    'naac_grade', 'ugc_approved', 'ugc_status', 'mode_of_learning', 'mode',
    'starting_fee', 'total_fee', 'num_programs', 'num_specializations',
    'duration', 'validity', 'emi_amount', 'admission_fee_note',
    'programs_intro', 'specializations_intro', 'eligibility_summary',
    'certificate_description', 'faculty_intro',
    'seo_title', 'meta_description',
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

def validate_payload(payload: dict[str, Any], page_type: str) -> dict[str, Any]:
    """Validate the extracted payload and return a quality report."""
    fields_list = ACF_FIELDS.get(page_type, [])
    # We validate all fields listed in ACF_FIELDS for this page_type
    required_fields = [f['key'] for f in fields_list]
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

    return {
        "summary": {
            "total_required": total_required,
            "mapped": mapped,
            "thin": thin,
            "missing": missing,
            "quality_score": quality_score,
        },
        "field_report": field_report,
    }


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
