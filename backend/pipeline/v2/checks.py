"""Validation of v2's extracted payload: checks that flag, never guesses.

Each flag is {"field_key", "code", "severity", "message"}:

* error   - what would show on the page is wrong (e.g. a fee row as heading)
* warning - probably wrong; a person should look (e.g. value not found in doc)
* info    - a deterministic step changed the value (placeholder -> null, ...)

Flags go into the validation report (field_report[i].flags) and lower the
field's confidence in field_mappings.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Iterable

from pipeline.enricher import _amount_value, specialization_from_title

ERROR, WARNING, INFO = "error", "warning", "info"

_TAG_RE = re.compile(r"<[^>]+>")
_MONEY_RE = re.compile(r"(₹|\binr\b|\brs\.?\s|\d[\d,]*\s*/-|\b\d{1,3}(?:,\d{2,3}){1,}\b)", re.I)
_DIGIT_RE = re.compile(r"\d")
_STEP_RE = re.compile(r"^\s*(?:<strong>)?\s*step\s*\d+", re.I)
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9&'+.-]*")
# Year/semester labels the syllabus structure needs even when the document only implies them.
_STRUCTURAL_RE = re.compile(r"^(year|semester|sem\.?)\s*[ivx\d]+$", re.I)
_CLAIM_RE = re.compile(r"\b(guarantee[ds]?|assured|100\s?% placement)\b", re.I)

HTML_FIELDS = {"about_content", "why_choose_content", "admission_steps", "emi_content", "exam_content",
               "placement_content", "syllabus_content"}
MONEY_FIELDS = {"total_fee", "emi_amount", "starting_fee", "course_amount_range"}
MONEY_SUBFIELDS = {"fee_plans": "plan_amount", "programs_table": "program_fee", "other_specs": "other_spec_fee"}

# Sub-fields a row can't be shown without.
REQUIRED_SUBFIELDS: dict[str, tuple[str, ...]] = {
    "faqs": ("question", "answer"), "fee_plans": ("plan_name", "plan_amount"), "job_profiles": ("job_title",),
    "other_specs": ("other_spec_name",), "programs_table": ("program_name",), "accreditations": ("body_name",),
    "course_accreditations": ("course_body_name",), "facts": ("fact_title", "fact_description"),
    "highlights": ("highlight_title",), "eligibility_content": ("eligibility_description",),
    "faculty_members": ("member_name",), "reviews": ("review_text",), "specialization": ("specialization_name",),
    "examination_process": ("exam_process_title", "exam_process_description"),
}

# Repeaters normally copied from one table: (key sub-field) for completeness checks.
TABLE_REPEATERS = {"programs_table": "program_name", "job_profiles": "job_title", "specialization": "specialization_name",
                   "faculty_members": "member_name", "other_specs": "other_spec_name"}

ACADEMIC = {"course": ("course_academic_years", "course_semesters", "course_semester_title", "course_semester_subjects"),
            "specialization": ("academic_years", "semesters", "semester_title", "semester_subjects")}

# Fields not taken from the document text, so not grounded against it.
UNGROUNDED = {"seo_title", "meta_description", "hero_description", "specialization_hero_description", "programs_intro",
              "eligibility_summary", "specialization_lowest_emi_strats_from", "course_syllabus_section_heading",
              "syllabus_section_heading", "num_programs", "num_specializations"}


def flag(field: str, code: str, severity: str, message: str) -> dict[str, str]:
    return {"field_key": field, "code": code, "severity": severity, "message": message}


def plain(value: Any) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG_RE.sub(" ", str(value or "")))).strip()


def normalize(text: str) -> str:
    """Lower-case text with markup, Markdown marks and digit grouping removed."""
    text = plain(text).lower()
    text = re.sub(r"[*#|`_>\[\]]", " ", text)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"[“”\"‘’]", "'", text)
    return re.sub(r"\s+", " ", text).strip()


# ── single-value checks ──────────────────────────────────────────────

def heading_problem(text: str) -> str | None:
    """Why this is not a usable heading, or None."""
    t = plain(text)
    if not t:
        return None
    if len(t) > 90:
        return "longer than 90 characters"
    if _MONEY_RE.search(t):
        return "contains a fee/amount (looks like a table row)"
    if re.match(r"^\[[^\]]+\]", t):
        return "still has a [tag] prefix"
    if t.endswith(".") and len(t.split()) > 4:
        return "reads like a sentence"
    return None


def is_usable_heading(text: str) -> bool:
    return bool(plain(text)) and heading_problem(text) is None


def has_amount(text: Any) -> bool:
    return bool(_DIGIT_RE.search(plain(text)))


def _steps(steps_html: str) -> list[str]:
    return [plain(li) for li in re.findall(r"<li[^>]*>(.*?)</li>", steps_html or "", re.I | re.S)]


# ── grounding ────────────────────────────────────────────────────────

# Short row labels the guide asks the model to write when the document has none.
LABEL_SUBFIELDS = {"eligibility_title", "fact_title", "highlight_title", "exam_process_title", "exam_card_title"}


def _strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in LABEL_SUBFIELDS:
                yield from _strings(v)


def grounding_problem(value: str, doc_norm: str, doc_words: set[str]) -> str | None:
    """Why this value doesn't look like it came from the document, or None."""
    text = normalize(value)
    if not text or text in doc_norm or _STRUCTURAL_RE.match(plain(value)):
        return None
    missing_numbers = [n for n in _NUMBER_RE.findall(text) if n.replace(",", "") not in doc_norm]
    if missing_numbers:
        return f"number(s) not in the document: {', '.join(missing_numbers[:4])}"
    words = [w.strip(".'") for w in _WORD_RE.findall(text) if len(w) > 3]
    if not words:
        return None
    found = sum(1 for w in words if w in doc_words)
    coverage = found / len(words)
    limit = 0.8 if len(words) > 12 else 0.6
    if coverage < limit:
        return f"only {coverage:.0%} of its words appear in the document"
    return None


# ── the full pass ────────────────────────────────────────────────────

def check_payload(payload: dict[str, Any], page_type: str, markdown: str, title: str,
                  tables: list[list[list[str]]] | None = None,
                  generated: Iterable[str] = ()) -> list[dict[str, str]]:
    """`generated`: fields written after extraction (not grounded against the document)."""
    skip_grounding = UNGROUNDED | set(generated)
    flags: list[dict[str, str]] = []
    # Names come from the document title, so the title counts as document text.
    doc_norm = normalize(f"{title}\n{markdown}")
    doc_words = set(w.strip(".'") for w in _WORD_RE.findall(doc_norm))

    for key, value in payload.items():
        if value is None or key.startswith("_"):
            continue
        # headings
        if key.endswith("_heading") and isinstance(value, str):
            problem = heading_problem(value)
            if problem:
                flags.append(flag(key, "heading_format", ERROR, f"Heading {problem}: {plain(value)[:80]!r}"))
        # money
        if key in MONEY_FIELDS and not has_amount(value):
            flags.append(flag(key, "money_without_amount", ERROR, f"No amount in {plain(value)[:60]!r}"))
        if key in MONEY_SUBFIELDS and isinstance(value, list):
            sub = MONEY_SUBFIELDS[key]
            bad = [plain(r.get(sub)) for r in value if isinstance(r, dict) and r.get(sub) and not has_amount(r.get(sub))]
            if bad:
                flags.append(flag(key, "money_without_amount", ERROR, f"{sub} without an amount: {bad[:3]}"))
        # HTML that repeats its own heading (a syllabus may open with "Year I" / "Semester I")
        lead = re.match(r"^\s*<h[1-6][^>]*>(.*?)</h[1-6]>", value, re.I | re.S) if key in HTML_FIELDS and isinstance(value, str) else None
        if lead and not _STRUCTURAL_RE.match(plain(lead.group(1))):
            flags.append(flag(key, "starts_with_heading", WARNING, "Content starts with a heading (it would show twice)."))
        # repeater rows missing what they need
        if key in REQUIRED_SUBFIELDS and isinstance(value, list):
            need = REQUIRED_SUBFIELDS[key]
            incomplete = [i + 1 for i, r in enumerate(value) if not isinstance(r, dict) or not all(r.get(s) for s in need)]
            if incomplete:
                flags.append(flag(key, "row_missing_subfield", WARNING, f"Row(s) {incomplete[:6]} lack {', '.join(need)}."))
        # unsupported placement claims
        if isinstance(value, str) and _CLAIM_RE.search(plain(value)) and not _CLAIM_RE.search(markdown):
            flags.append(flag(key, "unsupported_claim", ERROR, "Claims guaranteed/assured placement; the document doesn't."))
        # grounding
        if key not in skip_grounding and not key.endswith("_heading"):
            for text in _strings(value):
                problem = grounding_problem(text, doc_norm, doc_words)
                if problem:
                    flags.append(flag(key, "not_in_document", WARNING, f"{problem} ({plain(text)[:60]!r})"))
                    break

    flags += _count_checks(payload)
    flags += _admission_checks(payload)
    flags += _fee_checks(payload)
    flags += _name_checks(payload, page_type, title)
    flags += _syllabus_checks(payload, page_type)
    flags += _completeness_checks(payload, tables or [], own_name=str(payload.get("spec_name") or ""))
    flags += _partner_checks(payload, page_type)
    return flags


COUNTED = {"num_programs": "programs_table", "num_specializations": "specialization"}


def _count_checks(payload: dict[str, Any]) -> list[dict[str, str]]:
    """A stated count that contradicts the list it counts (UPES: 'Number of Programs: 5', 6 programs listed)."""
    flags = []
    for key, list_key in COUNTED.items():
        rows = payload.get(list_key)
        m = re.search(r"\d+", plain(payload.get(key)))
        if not m or not isinstance(rows, list) or not rows:
            continue
        stated, listed = int(m.group(0)), len(rows)
        plus = "+" in plain(payload.get(key))
        if (plus and listed < stated) or (not plus and listed != stated):
            flags.append(flag(key, "count_mismatch", WARNING,
                              f"States {plain(payload.get(key))!r} but {list_key} lists {listed}."))
    return flags


def _admission_checks(payload: dict[str, Any]) -> list[dict[str, str]]:
    flags = []
    steps_html = payload.get("admission_steps")
    if isinstance(steps_html, str) and steps_html.strip():
        lists = re.findall(r"<(ol|ul)\b", steps_html, re.I)
        if not lists:
            flags.append(flag("admission_steps", "steps_not_a_list", ERROR, "Steps are not an ordered list (<ol>)."))
        elif len(lists) > 1:
            flags.append(flag("admission_steps", "steps_more_than_one_list", ERROR,
                              "More than one list; a later list (notes/instructions) would show as extra steps."))
        if re.search(r"<li[^>]*>\s*(?:<strong>)?\s*(additional information|important instructions?|note)\b", steps_html, re.I):
            flags.append(flag("admission_steps", "note_inside_steps", ERROR, "A note/instruction is listed as a step."))
    note = payload.get("admission_fee_note")
    if isinstance(note, str) and note.strip():
        note_text = plain(note)
        steps = [s.lower().rstrip(".") for s in _steps(steps_html or "")]
        if _STEP_RE.match(note_text) or any(note_text.lower().rstrip(".") == s or (len(note_text) > 15 and note_text.lower().rstrip(".") in s) for s in steps):
            flags.append(flag("admission_fee_note", "note_is_a_step", ERROR, "The note repeats one of the steps."))
    return flags


def _fee_checks(payload: dict[str, Any]) -> list[dict[str, str]]:
    flags = []
    plans = payload.get("fee_plans")
    if not isinstance(plans, list):
        return flags
    names = [str(r.get("plan_name") or "").strip().lower() for r in plans if isinstance(r, dict)]
    if any("emi" in n.split() for n in names):
        flags.append(flag("fee_plans", "emi_as_plan", ERROR, "EMI is listed as a fee plan (it has its own field)."))
    repeated = sorted({n for n in names if n and names.count(n) > 1})
    if repeated:
        flags.append(flag("fee_plans", "plan_name_repeated", WARNING,
                          f"Plan name(s) repeated without their column: {repeated[:3]}"))
    totals = [r for r in plans if isinstance(r, dict) and "total" in str(r.get("plan_name") or "").lower()
              and _amount_value(str(r.get("plan_amount") or ""))]
    if totals and payload.get("total_fee"):
        lowest = min(_amount_value(str(r["plan_amount"])) for r in totals)
        if _amount_value(str(payload["total_fee"])) != lowest:
            flags.append(flag("total_fee", "total_not_lowest_total", ERROR,
                              f"total_fee {plain(payload['total_fee'])!r} is not the lowest Total row ({lowest:,})."))
    return flags


def _name_checks(payload: dict[str, Any], page_type: str, title: str) -> list[dict[str, str]]:
    if page_type != "specialization":
        return []
    from_title = specialization_from_title(title or "")
    name = str(payload.get("spec_name") or "")
    if from_title and from_title.lower() not in name.lower():
        return [flag("spec_name", "name_not_from_title", ERROR,
                     f"spec_name {name!r} doesn't match the document title ({from_title!r}).")]
    return []


def _syllabus_checks(payload: dict[str, Any], page_type: str) -> list[dict[str, str]]:
    if page_type not in ACADEMIC:
        return []
    years_key, sems_key, title_key, subjects_key = ACADEMIC[page_type]
    years = payload.get(years_key)
    if not isinstance(years, list):
        return []
    flags = []
    semesters = [s for y in years if isinstance(y, dict) for s in (y.get(sems_key) or []) if isinstance(s, dict)]
    empty = [plain(s.get(title_key)) or "?" for s in semesters if not _steps(str(s.get(subjects_key) or "")) and not plain(s.get(subjects_key))]
    if empty:
        flags.append(flag(years_key, "semester_without_subjects", ERROR, f"No subjects for: {empty[:4]}"))
    html = payload.get("syllabus_content")
    if isinstance(html, str) and html.strip():
        flat_subjects = len(re.findall(r"<li\b", html, re.I))
        repeater_subjects = sum(len(re.findall(r"<li\b", str(s.get(subjects_key) or ""), re.I)) for s in semesters)
        if flat_subjects and repeater_subjects and flat_subjects != repeater_subjects:
            flags.append(flag(years_key, "subject_count_mismatch", WARNING,
                              f"{repeater_subjects} subjects in the year/semester list but {flat_subjects} in syllabus_content."))
    return flags


def _first_cells(tables: list[list[list[str]]]) -> list[list[str]]:
    return [[normalize(r[0]) for r in t[1:] if r and normalize(r[0])] for t in tables if len(t) > 1]


def _completeness_checks(payload: dict[str, Any], tables: list[list[list[str]]], own_name: str = "") -> list[dict[str, str]]:
    flags = []
    columns = _first_cells(tables)
    for key, sub in TABLE_REPEATERS.items():
        rows = payload.get(key)
        if not isinstance(rows, list) or not rows:
            continue
        names = {normalize(r.get(sub)) for r in rows if isinstance(r, dict) and r.get(sub)}
        best = max(columns, key=lambda col: len(names & set(col)), default=[])
        if len(names & set(best)) < 2:
            continue
        missing = [c for c in best if c not in names and not re.match(r"^(all\b|total\b)", c)
                   and not (key == "other_specs" and own_name and c == normalize(own_name))]
        if missing:
            flags.append(flag(key, "rows_missing", ERROR, f"{len(missing)} table row(s) not extracted: {missing[:4]}"))
    return flags


def _partner_checks(payload: dict[str, Any], page_type: str) -> list[dict[str, str]]:
    key = {"course": "top_hiring_partners_course", "specialization": "hiring_partners_specialization"}.get(page_type)
    value = payload.get(key) if key else None
    if not isinstance(value, str) or not value.strip():
        return []
    flags = []
    if re.search(r"\betc\.?", value, re.I):
        flags.append(flag(key, "partners_etc", WARNING, "Partner list still contains 'etc.'."))
    if "&amp;" in value or "<" in value:
        flags.append(flag(key, "partners_markup", WARNING, "Partner names contain HTML or entities."))
    return flags


_GENERATED_LENGTHS = {"seo_title": (40, 65), "meta_description": (120, 170),
                      "hero_description": (60, 320), "specialization_hero_description": (60, 320)}


def check_generated(payload: dict[str, Any], page_type: str, keys: Iterable[str]) -> list[dict[str, str]]:
    """Length and name checks for texts written after extraction."""
    from pipeline.v2.field_guide import PAGE_NAME_FIELD

    flags = []
    name = str(payload.get(PAGE_NAME_FIELD.get(page_type, "university_name")) or "")
    for key in keys:
        text = plain(payload.get(key))
        if not text:
            continue
        lo, hi = _GENERATED_LENGTHS.get(key, (1, 10_000))
        if not lo <= len(text) <= hi:
            flags.append(flag(key, "generated_length", WARNING, f"{len(text)} characters (expected {lo}-{hi})."))
        if key == "seo_title" and name and name.lower() not in text.lower():
            flags.append(flag(key, "generated_without_name", WARNING, f"Doesn't contain the page name {name!r}."))
    return flags


def adjusted_confidence(base: float, field_flags: list[dict[str, str]]) -> float:
    """Model confidence lowered by this field's flags."""
    score = base
    for f in field_flags:
        if f["severity"] == ERROR:
            score = min(score, 0.3)
        elif f["severity"] == WARNING:
            score -= 0.2
    return round(max(score, 0.1), 2)
