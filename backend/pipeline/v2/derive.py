"""Deterministic steps after v2's extraction call: exact maths and copies only.

Nothing here guesses at content. It covers:

* specialization-wise fee tables -> course `specialization` rows and
  `course_amount_range`, specialization `other_specs` fees and own
  `total_fee` (v1's enricher functions, reused unchanged, fed from v2's
  tables);
* copies WordPress needs in two places (syllabus section heading,
  lowest-EMI number, one-line eligibility summary);
* placeholder values -> null;
* the "<page name> <Label>" heading fallback, only for empty or unusable
  headings of sections that have content.

Every change is returned as a record so the Mapping screen can show it.
"""

from __future__ import annotations

import re
from typing import Any

from pipeline.docx_parser import _parse_standard_table, _skip_merged_title_rows
from pipeline.enricher import _derive_specialization_fees, specialization_from_title, summarize_eligibility
from pipeline.v2.field_guide import HEADING_LABELS, PAGE_NAME_FIELD

PLACEHOLDER_RE = re.compile(
    r"^\s*(n/?a|na|nil|none|null|not available|not applicable|not mentioned|not specified|-+|—|–)\s*\.?\s*$", re.I)
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{2,3})+|\d{4,}")

# heading field -> the content field(s) it titles (first one valid for the page type wins)
HEADING_CONTENT: dict[str, tuple[str, ...]] = {
    "about_heading": ("about_content",), "why_choose_heading": ("why_choose_content",),
    "facts_heading": ("facts",), "accreditations_heading": ("accreditations", "course_accreditations"),
    "programs_heading": ("programs_table",), "admission_heading": ("admission_steps",),
    "emi_heading": ("emi_content",), "exam_heading": ("exam_content", "examination_process"),
    "faculty_heading": ("faculty_members", "faculty_intro"), "placement_heading": ("placement_content",),
    "reviews_heading": ("reviews",), "faqs_heading": ("faqs",), "highlights_heading": ("highlights",),
    "specializations_heading": ("specialization", "specializations_intro"), "fee_heading": ("fee_plans", "total_fee"),
    "eligibility_heading": ("eligibility_content",), "syllabus_heading": ("syllabus_content", "course_academic_years", "academic_years"),
    "jobs_heading": ("job_profiles", "jobs_content"), "certificate_heading": ("certificate_description",),
    "other_specs_heading": ("other_specs",),
}

SYLLABUS_COPY = {"course": "course_syllabus_section_heading", "specialization": "syllabus_section_heading"}


def _record(field: str, rule: str) -> dict[str, str]:
    return {"field_key": field, "rule": rule}


def tables_as_section_map(tables: list[list[list[str]]]) -> dict[str, Any]:
    """v2 tables (rows of cell text) in the shape v1's fee functions read."""
    sections: dict[str, Any] = {}
    for i, rows in enumerate(tables, 1):
        rows = _skip_merged_title_rows([[c or "" for c in r] for r in rows])
        data = _parse_standard_table(rows)
        if data:
            sections[f"v2 table {i}"] = {"content": {"tables": [{"data": data}]}}
    return sections


def apply_specialization_fees(payload: dict[str, Any], tables: list[list[list[str]]], page_type: str) -> list[dict[str, str]]:
    """Exact fee-table maths (see enricher._derive_specialization_fees)."""
    log: list[dict[str, str]] = []
    _derive_specialization_fees(payload, tables_as_section_map(tables), page_type, log)
    return [_record(e["field_key"], e["source"]) for e in log]


def null_placeholders(payload: dict[str, Any]) -> list[dict[str, str]]:
    changes = []
    for key, value in payload.items():
        if isinstance(value, str) and PLACEHOLDER_RE.match(value):
            payload[key] = None
            changes.append(_record(key, "placeholder->null"))
        elif isinstance(value, list):
            for row in value:
                if isinstance(row, dict):
                    for sub, v in row.items():
                        if isinstance(v, str) and PLACEHOLDER_RE.match(v):
                            row[sub] = None
                            changes.append(_record(key, f"placeholder->null:{sub}"))
    return changes


def page_name(payload: dict[str, Any], page_type: str) -> str:
    return str(payload.get(PAGE_NAME_FIELD.get(page_type, "university_name")) or payload.get("university_name") or "").strip()


def apply_heading_fallbacks(payload: dict[str, Any], page_type: str, valid_keys: set[str],
                            is_usable_heading) -> list[dict[str, str]]:
    """Empty or unusable headings of sections that have content -> '<page name> <Label>'."""
    changes = []
    name = page_name(payload, page_type)
    for heading_key, content_keys in HEADING_CONTENT.items():
        if heading_key not in valid_keys:
            continue
        if not any(payload.get(c) for c in content_keys if c in valid_keys):
            continue
        current = payload.get(heading_key)
        if current and is_usable_heading(current):
            continue
        label = HEADING_LABELS[heading_key]
        payload[heading_key] = f"{name} {label}".strip() if name else label
        changes.append(_record(heading_key, "heading_fallback" if not current else "heading_unusable->fallback"))
    return changes


_LINK_RE = re.compile(r"^[\s*_]*linked[\s_]*(university|course|program)[\s*_]*\s*[-:–—]\s*(.+?)\s*$", re.I | re.M)


def relationship_hints(markdown: str) -> dict[str, str]:
    """'Linked_university - UPES Online' lines -> {'linked_university': 'UPES Online'}.

    Same signal v1's key-value pass captured; build_json_output stores it in
    _meta.relationship_hints for the publish-time post-title match.
    """
    hints: dict[str, str] = {}
    for kind, name in _LINK_RE.findall(markdown or ""):
        key = "linked_university" if kind.lower() == "university" else "linked_course"
        name = re.sub(r"[*_]+$", "", name).strip()
        if name and key not in hints:
            hints[key] = name
    return hints


def apply_title_name(payload: dict[str, Any], page_type: str, filename: str) -> list[dict[str, str]]:
    """spec_name comes from the document title ('… Online MCA in DevOps' -> 'DevOps').

    Same rule as v1 (enricher.specialization_from_title): a name the title
    confirms is kept, one it contradicts is replaced.
    """
    if page_type != "specialization":
        return []
    from_title = specialization_from_title(filename)
    current = str(payload.get("spec_name") or "")
    if from_title and from_title.lower() not in current.lower():
        payload["spec_name"] = from_title
        return [_record("spec_name", "title_name")]
    return []


def apply_copies(payload: dict[str, Any], page_type: str) -> list[dict[str, str]]:
    changes = []
    target = SYLLABUS_COPY.get(page_type)
    if target and payload.get("syllabus_heading") and not payload.get(target):
        payload[target] = payload["syllabus_heading"]
        changes.append(_record(target, "copy:syllabus_heading"))
    if page_type == "specialization" and payload.get("emi_amount") and not payload.get("specialization_lowest_emi_strats_from"):
        m = _AMOUNT_RE.search(str(payload["emi_amount"]))
        if m:
            payload["specialization_lowest_emi_strats_from"] = m.group(0)  # "INR 10,156/-" -> "10,156"
            changes.append(_record("specialization_lowest_emi_strats_from", "copy:emi_amount"))
    if page_type in ("course", "specialization") and not payload.get("eligibility_summary"):
        summary = summarize_eligibility(payload.get("eligibility_content"))
        if summary:
            payload["eligibility_summary"] = summary
            changes.append(_record("eligibility_summary", "summarize:eligibility_content"))
    return changes
