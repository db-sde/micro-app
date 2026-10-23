"""The JSON Schema for v2's single extraction call, per page type.

Fields = our registry (acf/fields.py ACF_FIELDS + V2_PUBLISHED_FIELDS +
V2_UNPUBLISHED_FIELDS), minus what is never in a document (images, files,
relations), what is written after extraction (SEO, hero texts), and what
is copied deterministically. The live WordPress schema (wp_schema) is the
check that every extracted field has somewhere to go.

Structured outputs allow at most 16 nullable/union fields and 24 optional
fields per request, so nothing here is nullable or optional: an absent
value is "" or [], turned into None by to_payload().

Output shape::

    {"values": {field: value, ...},
     "provenance": [{"field", "heading", "confidence"}, ...],
     "notes": [str, ...]}
"""

from __future__ import annotations

from typing import Any

from acf.fields import (
    ACF_FIELDS, V2_PUBLISHED_FIELDS, V2_UNPUBLISHED_FIELDS,
    HTML, JSON_ARRAY, NON_EXTRACTABLE_TYPES,
)
from pipeline.v2.field_guide import describe

CONFIDENCE_LEVELS = ("high", "medium", "low")
CONFIDENCE_SCORE = {"high": 0.95, "medium": 0.75, "low": 0.5}

# Written after extraction from the final values (pipeline/v2/generate.py).
GENERATED_FIELDS: dict[str, set[str]] = {
    "university": {"seo_title", "meta_description", "programs_intro"},
    "course": {"seo_title", "meta_description"},
    "specialization": {"seo_title", "meta_description"},
}

# Taken from the document when the writers wrote it (e.g. a [hero_description]
# section), otherwise written after extraction like the fields above.
GENERATED_IF_MISSING: dict[str, set[str]] = {
    "university": {"hero_description"},
    "course": {"hero_description"},
    "specialization": {"specialization_hero_description"},
}

# Copied or computed deterministically after extraction (pipeline/v2/derive.py).
DERIVED_FIELDS: dict[str, set[str]] = {
    "university": set(),
    "course": {"eligibility_summary", "course_syllabus_section_heading"},
    "specialization": {"eligibility_summary", "syllabus_section_heading", "specialization_lowest_emi_strats_from"},
}


def field_defs(page_type: str) -> list[dict[str, Any]]:
    """Every field definition v2 knows for a page type, registry order."""
    return [*ACF_FIELDS.get(page_type, []), *V2_PUBLISHED_FIELDS.get(page_type, []),
            *V2_UNPUBLISHED_FIELDS.get(page_type, [])]


def extracted_fields(page_type: str) -> list[dict[str, Any]]:
    """The fields the model fills."""
    skip = GENERATED_FIELDS.get(page_type, set()) | DERIVED_FIELDS.get(page_type, set())
    return [f for f in field_defs(page_type) if f["type"] not in NON_EXTRACTABLE_TYPES and f["key"] not in skip]


def field_type(page_type: str, key: str) -> str | None:
    return next((f["type"] for f in field_defs(page_type) if f["key"] == key), None)


def _row_schema(sub_fields: list[dict[str, Any]]) -> dict[str, Any]:
    props: dict[str, Any] = {}
    for sub in sub_fields:
        if sub["type"] == JSON_ARRAY:
            props[sub["key"]] = {"type": "array", "items": _row_schema(sub.get("sub_fields") or [])}
        else:
            props[sub["key"]] = {"type": "string"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


# Year -> semester syllabus repeaters are asked for as flat rows (one per
# semester) and nested again in to_payload: a list inside a list made the
# compiled grammar too large for course and specialization pages.
NESTED_FLAT: dict[str, tuple[str, str, str, str]] = {
    # field: (year title key, semesters key, semester title key, subjects key)
    "course_academic_years": ("course_year_title", "course_semesters", "course_semester_title", "course_semester_subjects"),
    "academic_years": ("year_title", "semesters", "semester_title", "semester_subjects"),
}


def _value_schema(page_type: str, f: dict[str, Any]) -> dict[str, Any]:
    if f["key"] in NESTED_FLAT:
        year, _, title, subjects = NESTED_FLAT[f["key"]]
        props = {year: {"type": "string"}, title: {"type": "string"}, subjects: {"type": "string"}}
        schema: dict[str, Any] = {"type": "array", "items": {"type": "object", "properties": props,
                                                              "required": list(props), "additionalProperties": False}}
    elif f["type"] == JSON_ARRAY:
        schema = {"type": "array", "items": _row_schema(f.get("sub_fields") or [])}
    else:
        schema = {"type": "string"}
    text = describe(page_type, f["key"])
    if f["type"] == HTML and "HTML" not in text:
        text = (text + " " if text else "") + "Clean HTML using only <p> <ul> <ol> <li> <strong> <em> <h3> <h4>."
    if text:
        schema["description"] = text
    return schema


def field_groups(page_type: str) -> list[list[str]]:
    """Fields split into two requests when one schema is too large: text fields, then lists."""
    fields = extracted_fields(page_type)
    groups = [[f["key"] for f in fields if f["type"] != JSON_ARRAY], [f["key"] for f in fields if f["type"] == JSON_ARRAY]]
    return [g for g in groups if g]


def output_schema(page_type: str, keys: list[str] | None = None) -> dict[str, Any]:
    fields = [f for f in extracted_fields(page_type) if keys is None or f["key"] in keys]
    keys = [f["key"] for f in fields]
    values = {f["key"]: _value_schema(page_type, f) for f in fields}
    return {
        "type": "object",
        "properties": {
            "values": {"type": "object", "properties": values, "required": keys, "additionalProperties": False},
            "provenance": {
                "type": "array",
                "description": "One entry per field you filled: the document heading it came from (as written, or '' if none) and your confidence.",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "description": "the field's key, as in values"},
                        "heading": {"type": "string"},
                        "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
                    },
                    "required": ["field", "heading", "confidence"],
                    "additionalProperties": False,
                },
            },
            "notes": {
                "type": "array",
                "description": "Short notes about anything in the document that did not fit a field or looked contradictory.",
                "items": {"type": "string"},
            },
        },
        "required": ["values", "provenance", "notes"],
        "additionalProperties": False,
    }


def _empty(value: Any) -> bool:
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return value is None


def _clean_rows(rows: list[Any]) -> list[Any]:
    """Strip strings, "" -> None, and drop rows that end up entirely blank (at any depth)."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            if not _empty(row):
                out.append(row)
            continue
        cleaned: dict[str, Any] = {}
        for k, v in row.items():
            if isinstance(v, list):
                cleaned[k] = _clean_rows(v)
            elif isinstance(v, str):
                cleaned[k] = v.strip() or None
            else:
                cleaned[k] = v
        if any(v not in (None, []) for v in cleaned.values()):
            out.append(cleaned)
    return out


def nest_semesters(key: str, rows: list[Any]) -> list[dict[str, Any]]:
    """Flat semester rows -> years with their semesters, in document order.

    Rows already nested (answers from before the flat schema) pass through.
    A row without a year title belongs to the year before it.
    """
    year_key, sems_key, title_key, subjects_key = NESTED_FLAT[key]
    if any(isinstance(r, dict) and sems_key in r for r in rows):
        return rows
    years: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        year = str(row.get(year_key) or "").strip()
        if not years or (year and year != years[-1][year_key]):
            years.append({year_key: year, sems_key: []})
        years[-1][sems_key].append({title_key: row.get(title_key, ""), subjects_key: row.get(subjects_key, "")})
    return years


def to_payload(page_type: str, values: dict[str, Any]) -> dict[str, Any]:
    """Model values -> payload: "" / [] become None, blank rows are dropped."""
    payload: dict[str, Any] = {}
    for f in extracted_fields(page_type):
        value = values.get(f["key"])
        if isinstance(value, list) and f["key"] in NESTED_FLAT:
            value = nest_semesters(f["key"], value)
        if isinstance(value, list):
            payload[f["key"]] = _clean_rows(value) or None
        elif isinstance(value, str):
            payload[f["key"]] = value.strip() or None
        else:
            payload[f["key"]] = None
    return payload
