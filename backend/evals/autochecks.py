"""Stress checks generated from each document's own structure (no model involved).

    cd backend && python -m evals.autochecks            # write auto_checks into every case.json
    python -m evals.autochecks --print jamia-mba        # show them without writing

Rules (each produces a check only when the document clearly has the shape):
* admission: "Step N" lines in the admission section -> number of steps,
  first and last step present; an amount written after the last step ->
  in the note and (if no step mentions it) not in the steps;
* tables: job roles -> job_profiles rows; faculty -> faculty_members rows;
  programs + fees (university) -> programs_table rows; a specialization-wise
  fee table -> specialization rows (course) or other_specs rows (specialization,
  minus the page's own); "All Specializations" rows are shared fees, not rows;
* syllabus tables: subjects per semester, in order;
* names: the specialization from the title; the [university_name] heading.

Hand-written checks stay in "checks"; these go in "auto_checks" and are
re-generated freely.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any

from evals.cases import Case, load_cases

_STEP_RE = re.compile(r"^\s*(?:[-*]\s+)?(?:\*\*)?\s*Step\s*(\d+)\s*[.:)\-–]?\s*(.*)$", re.I)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_AMOUNT_RE = re.compile(r"(?:INR|₹|Rs\.?)\s*\d[\d,]*(?:\s*/-)?", re.I)
_SEM_RE = re.compile(r"^\s*(?:\*\*)?\s*(semester|sem\.?)\s*[ivx\d]+", re.I)
_CATCH_ALL_RE = re.compile(r"^\s*all\b", re.I)


def _plain(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[*_`]|<[^>]+>|\[[^\]]*\]", " ", text)).strip()


def _section(markdown: str, keyword: str) -> list[str]:
    """Lines of the first section whose heading contains `keyword`, up to the next heading at its level or above."""
    lines = markdown.splitlines()
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if m and keyword in m.group(2).lower():
            level = len(m.group(1))
            out = []
            for nxt in lines[i + 1:]:
                h = _HEADING_RE.match(nxt)
                if h and len(h.group(1)) <= level:
                    break
                out.append(nxt)
            return out
    return []


def admission_checks(markdown: str) -> list[dict[str, Any]]:
    section = _section(markdown, "admission")
    steps = [(i, _STEP_RE.match(line)) for i, line in enumerate(section)]
    steps = [(i, m) for i, m in steps if m]
    numbers = [int(m.group(1)) for _, m in steps]
    if len(steps) < 2 or numbers != list(range(1, len(numbers) + 1)):
        return []
    first, last = _plain(steps[0][1].group(0)), _plain(steps[-1][1].group(0))
    checks = [
        {"type": "html_list_items", "field": "admission_steps", "equals": len(steps), "auto": "admission step lines"},
        {"type": "contains", "field": "admission_steps", "phrases": [first[:45].strip(), last[:45].strip()], "auto": "first and last step"},
    ]
    after = " ".join(section[steps[-1][0] + 1:])
    steps_text = " ".join(_plain(m.group(0)) for _, m in steps)
    amounts = [a.strip() for a in _AMOUNT_RE.findall(after)]
    if amounts:
        amount = re.sub(r"\s*/-$", "", amounts[0]).strip()
        checks.append({"type": "contains", "field": "admission_fee_note", "phrases": [amount], "auto": "amount after the last step"})
        if amount not in steps_text:
            checks.append({"type": "not_contains", "field": "admission_steps", "phrases": [amount], "auto": "note is not a step"})
    return checks


def _data_rows(table: list[list[str]]) -> list[list[str]]:
    return [r for r in table[1:] if r and _plain(r[0]) and len({c for c in r if c.strip()}) > 1 or (r and _plain(r[0]) and len(r) == 1)]


def table_checks(tables: list[list[list[str]]], page_type: str, own_spec: str | None) -> list[dict[str, Any]]:
    checks = []
    for table in tables:
        if len(table) < 3:
            continue
        header = [c.lower() for c in table[0]]
        joined = " ".join(header)
        rows = _data_rows(table)
        if any("job" in h or "profile" in h for h in header) and any("salar" in h for h in header):
            checks.append({"type": "row_count", "field": "job_profiles", "equals": len(rows), "auto": "job roles table"})
        elif page_type == "university" and "faculty" in joined:
            checks.append({"type": "row_count", "field": "faculty_members", "equals": len(rows), "auto": "faculty table"})
        elif page_type == "university" and ("course" in header[0] or "program" in header[0]) and "fee" in joined:
            checks.append({"type": "row_count", "field": "programs_table", "equals": len(rows), "auto": "programs table"})
        elif "speciali" in header[0] and "fee" in joined and page_type in ("course", "specialization"):
            names = [_plain(r[0]) for r in rows if not _CATCH_ALL_RE.match(_plain(r[0]))]
            if page_type == "course":
                checks.append({"type": "row_count", "field": "specialization", "equals": len(names), "auto": "specialization fee table"})
            else:
                own = (own_spec or "").lower().strip()
                # The page's own row: the same or a longer name containing it first
                # ("Digital Marketing" is not "Marketing"); otherwise the longest
                # shorter name it contains ("Finance Management" page, "Finance" row).
                own_rows = [n for n in names if own and own in n.lower()]
                if not own_rows:
                    shorter = [n for n in names if own and n.lower() in own]
                    own_rows = [max(shorter, key=len)] if shorter else []
                others = [n for n in names if n not in own_rows]
                if len(others) < len(names):  # only when the page's own row was found
                    checks.append({"type": "row_count", "field": "other_specs", "equals": len(others), "auto": "specialization fee table minus own"})
        semesters = _syllabus_counts(table)
        if semesters:
            field = "course_academic_years" if page_type == "course" else "academic_years"
            if page_type in ("course", "specialization"):
                checks.append({"type": "semester_subjects", "field": field, "equals": semesters, "auto": "syllabus table"})
    return checks


def _syllabus_counts(table: list[list[str]]) -> list[int]:
    counts: list[int] = []
    for i, row in enumerate(table):
        if row and all(_SEM_RE.match(c) for c in row if c.strip()) and any(c.strip() for c in row) and i + 1 < len(table):
            nxt = table[i + 1]
            for cell in nxt[: len(row)]:
                items = [x for x in re.split(r"\n", cell) if _plain(x)]
                counts.append(len(items))
    return counts if len(counts) >= 2 and all(counts) else []


def name_checks(markdown: str, page_type: str, filename: str) -> list[dict[str, Any]]:
    from pipeline.enricher import specialization_from_title

    if page_type == "specialization":
        spec = specialization_from_title(filename)
        return [{"type": "equals", "field": "post_title", "value": spec, "auto": "specialization from the title"}] if spec else []
    if page_type == "university":
        m = re.search(r"(?m)^#{1,6}\s*\[university_name\]\s*(.+)$", markdown)
        if m:
            return [{"type": "equals", "field": "post_title", "value": _plain(m.group(1)), "auto": "[university_name] heading"}]
    return []


def generate(case: Case) -> list[dict[str, Any]]:
    from pipeline.enricher import specialization_from_title
    from pipeline.v2.markdown import to_markdown

    md = to_markdown(case.doc_bytes(), case.filename)
    own = specialization_from_title(case.filename) if case.page_type == "specialization" else None
    checks = name_checks(md.markdown, case.page_type, case.filename)
    checks += admission_checks(md.markdown)
    checks += table_checks(md.tables, case.page_type, own)
    seen, unique = set(), []
    for c in checks:
        key = (c["type"], c["field"])
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cases", nargs="*")
    parser.add_argument("--print", action="store_true", help="show, don't write")
    args = parser.parse_args(argv)
    for case in load_cases(ids=args.cases or None):
        checks = generate(case)
        if args.print:
            print(case.case_id, json.dumps(checks, indent=1, ensure_ascii=False))
            continue
        path = case.directory / "case.json"
        spec = json.loads(path.read_text(encoding="utf-8"))
        spec["auto_checks"] = checks
        path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"{case.case_id:28} {len(checks)} auto checks: " + ", ".join(f"{c['type']}:{c['field']}" for c in checks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
