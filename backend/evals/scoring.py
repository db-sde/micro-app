"""Field-by-field scoring of a projected WordPress ACF body against truth.

* short fields: normalized exact match; currency/formatting-only
  differences ("INR 1,30,000 /-" vs "₹1,30,000") count as a match;
* HTML / long text: word-level F1 (pass >= 0.85) plus required phrases
  from the case file;
* repeaters: rows matched on their key sub-field, row precision/recall,
  and per-sub-field accuracy on matched rows (nested rows recursively).

Statuses: match, mismatch, missed (truth has it, prediction empty),
invented (prediction has it, truth empty), both_empty (not scored).
"""

from __future__ import annotations

import difflib
import html as _html
import re
from typing import Any

from pipeline.v2.checks import check_payload

SHORT_PASS = 0.9
HTML_PASS = 0.85
ROW_MATCH = 0.8

GENERATED = {"seo_title", "meta_description", "hero_description", "specialization_hero_description", "programs_intro"}
NOT_SCORED_RE = re.compile(
    r"^(linked_university|linked_course|category_page|popularity_score|course_intake|video_.*|.*_thumbnail|"
    r"certificate_image.*|download_brochure_.*|hero_image)$")
KEY_SUBFIELDS = ("question", "plan_name", "job_title", "program_name", "other_spec_name", "specialization_name",
                 "body_name", "course_body_name", "member_name", "highlight_title", "eligibility_title",
                 "exam_process_title", "exam_card_title", "course_year_title", "year_title",
                 "course_semester_title", "semester_title", "review_text", "fact_title")

CATEGORIES: list[tuple[str, re.Pattern[str]]] = [
    ("names", re.compile(r"^(post_title|university_name|university_full_name|program_name|spec_name)$")),
    ("headings", re.compile(r"_heading$")),
    ("admission", re.compile(r"^admission_")),
    ("eligibility", re.compile(r"^eligibility_")),
    ("spec-wise fees", re.compile(r"^(specialization|course_amount_range|other_specs)$")),
    ("syllabus", re.compile(r"(syllabus|academic_years)")),
    ("fees", re.compile(r"(fee|plan_|payment|(^|_)emi(_|$)|price)")),
    ("jobs & placement", re.compile(r"(job|placement|partner)")),
    ("generated", re.compile(r"^(seo_title|meta_description|hero_description|specialization_hero_description|programs_intro)$")),
    ("stats", re.compile(r"^(duration|mode|mode_of_learning|naac_grade|nirf_rank.*|ugc_.*|validity|program_validity|"
                         r"program_duration|established_year|num_.*|duration_specialization)$")),
]

# Flag codes from pipeline.v2.checks -> report category.
CHECK_CATEGORIES = {
    "heading_format": "headings", "money_without_amount": "fees", "starts_with_heading": "headings",
    "row_missing_subfield": "repeaters", "unsupported_claim": "jobs & placement", "not_in_document": "grounding",
    "steps_not_a_list": "admission", "steps_more_than_one_list": "admission", "note_inside_steps": "admission",
    "note_is_a_step": "admission", "emi_as_plan": "fees", "plan_name_repeated": "fees",
    "total_not_lowest_total": "fees", "name_not_from_title": "names", "semester_without_subjects": "syllabus",
    "subject_count_mismatch": "syllabus", "rows_missing": "repeaters", "partners_etc": "jobs & placement",
    "partners_markup": "jobs & placement", "placeholder": "placeholders", "count_mismatch": "stats",
}

_PLACEHOLDER_RE = re.compile(r"^\s*(n/?a|na|nil|none|null|not available|not applicable|-+|—)\s*\.?\s*$", re.I)


def category(field: str) -> str:
    for name, pattern in CATEGORIES:
        if pattern.search(field):
            return name
    return "content"


def plain(value: Any) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))).strip()


def empty(value: Any) -> bool:
    if value is None or value is False:
        return True
    if isinstance(value, str):
        return not plain(value)
    if isinstance(value, (list, dict)):
        return not value
    return False


def norm(text: Any) -> str:
    t = plain(text).lower()
    t = t.replace("₹", " inr ").replace("rs.", " inr ").replace("/-", " ")
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"[^\w%+#&.]+", " ", t)
    return re.sub(r"\s+", " ", t).strip(" .")


def _amounts(text: str) -> list[int]:
    return sorted(int(n) for n in re.findall(r"\d{4,}", norm(text)))


def ratio(a: Any, b: Any) -> float:
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


def short_score(pred: Any, truth: Any) -> float:
    p, t = norm(pred), norm(truth)
    if p == t:
        return 1.0
    if _amounts(t) and _amounts(p) == _amounts(t):
        words = lambda s: set(re.sub(r"\d+", " ", s).split()) - {"inr"}  # noqa: E731
        if words(p) == words(t) or difflib.SequenceMatcher(None, " ".join(sorted(words(p))), " ".join(sorted(words(t)))).ratio() >= 0.6:
            return 1.0
    return round(ratio(pred, truth), 3)


def word_f1(pred: Any, truth: Any) -> float:
    p, t = norm(pred).split(), norm(truth).split()
    if not p or not t:
        return 0.0
    common: dict[str, int] = {}
    for w in t:
        common[w] = common.get(w, 0) + 1
    hit = 0
    for w in p:
        if common.get(w, 0) > 0:
            hit += 1
            common[w] -= 1
    if not hit:
        return 0.0
    precision, recall = hit / len(p), hit / len(t)
    return round(2 * precision * recall / (precision + recall), 3)


def kind_of(value: Any) -> str:
    if isinstance(value, list):
        return "repeater"
    if isinstance(value, str) and (re.search(r"<(p|li|ul|ol|h\d)\b", value, re.I) or len(plain(value)) > 160):
        return "html"
    return "short"


def _key(row: dict[str, Any]) -> str | None:
    return next((k for k in KEY_SUBFIELDS if k in row), next(iter(row), None))


def repeater_score(pred: list[Any], truth: list[Any]) -> dict[str, Any]:
    truth_rows = [r for r in truth if isinstance(r, dict) and not all(empty(v) for v in r.values())]
    pred_rows = [r for r in pred if isinstance(r, dict) and not all(empty(v) for v in r.values())]
    if not truth_rows or not pred_rows:
        return {"score": 0.0, "passed": False, "precision": 0.0, "recall": 0.0, "subfield_accuracy": 0.0,
                "missing_rows": [plain(r.get(_key(r))) for r in truth_rows][:6], "extra_rows": []}
    key = _key(truth_rows[0])
    pairs = sorted(((ratio(p.get(key), t.get(key)), i, j) for i, p in enumerate(pred_rows) for j, t in enumerate(truth_rows)),
                   reverse=True)
    used_p, used_t, matched = set(), set(), []
    for sim, i, j in pairs:
        if sim < ROW_MATCH:
            break
        if i in used_p or j in used_t:
            continue
        used_p.add(i)
        used_t.add(j)
        matched.append((pred_rows[i], truth_rows[j]))
    checks, passes = 0, 0
    for p_row, t_row in matched:
        for sub in set(t_row) | set(p_row):
            if sub == key or (empty(t_row.get(sub)) and empty(p_row.get(sub))):
                continue
            if sub not in t_row:
                continue  # sub-field WordPress doesn't have (e.g. plan_total)
            checks += 1
            passes += int(score_value(p_row.get(sub), t_row.get(sub))["passed"])
    precision, recall = len(matched) / len(pred_rows), len(matched) / len(truth_rows)
    f1 = 0.0 if not matched else 2 * precision * recall / (precision + recall)
    sub_acc = passes / checks if checks else 1.0
    return {"score": round(f1 * sub_acc, 3), "passed": recall == 1.0 and precision == 1.0 and sub_acc >= 0.9,
            "precision": round(precision, 3), "recall": round(recall, 3), "subfield_accuracy": round(sub_acc, 3),
            "missing_rows": [plain(t.get(key)) for j, t in enumerate(truth_rows) if j not in used_t][:6],
            "extra_rows": [plain(p.get(key)) for i, p in enumerate(pred_rows) if i not in used_p][:6]}


def score_value(pred: Any, truth: Any) -> dict[str, Any]:
    if empty(truth) and empty(pred):
        return {"status": "both_empty", "score": 1.0, "passed": True}
    if empty(pred):
        return {"status": "missed", "score": 0.0, "passed": False}
    if empty(truth):
        return {"status": "invented", "score": 0.0, "passed": False}
    kind = kind_of(truth) if not isinstance(pred, list) else "repeater"
    if kind == "repeater":
        if not isinstance(pred, list) or not isinstance(truth, list):
            return {"status": "mismatch", "score": 0.0, "passed": False, "detail": "shape differs"}
        detail = repeater_score(pred, truth)
        return {"status": "match" if detail["passed"] else "mismatch", "score": detail["score"],
                "passed": detail["passed"], "detail": detail}
    if kind == "html":
        f1 = word_f1(pred, truth)
        return {"status": "match" if f1 >= HTML_PASS else "mismatch", "score": f1, "passed": f1 >= HTML_PASS}
    s = short_score(pred, truth)
    return {"status": "match" if s >= SHORT_PASS else "mismatch", "score": s, "passed": s >= SHORT_PASS}


def _snippet(value: Any, limit: int = 160) -> str:
    if isinstance(value, list):
        text = "; ".join(plain(" | ".join(str(v) for v in r.values()) if isinstance(r, dict) else r) for r in value[:4])
        return f"[{len(value)} rows] {text}"[:limit]
    return plain(value)[:limit]


def score_case(pred_acf: dict[str, Any], truth_acf: dict[str, Any], pred_title: str | None = None,
               truth_title: str | None = None, ignore: set[str] | None = None) -> list[dict[str, Any]]:
    ignore = ignore or set()
    results = []
    keys = sorted(set(truth_acf) | set(pred_acf))
    for key in keys:
        truth, pred = truth_acf.get(key), pred_acf.get(key)
        if key in ignore or NOT_SCORED_RE.match(key) or isinstance(truth, (int, float, dict)) and not isinstance(truth, bool):
            continue
        if key not in truth_acf:
            continue  # field the live post doesn't have
        r = score_value(pred, truth)
        results.append({"field": key, "category": category(key), "generated": key in GENERATED,
                        "kind": kind_of(truth if not empty(truth) else pred), **r,
                        "expected": _snippet(truth), "actual": _snippet(pred)})
    if truth_title is not None:
        r = score_value(pred_title, plain(truth_title))
        results.append({"field": "post_title", "category": "names", "generated": False, "kind": "short", **r,
                        "expected": plain(truth_title), "actual": plain(pred_title)})
    return results


# ── case-file checks (stress assertions) ─────────────────────────────

def _subject_counts(years: Any) -> list[int]:
    counts = []
    for year in years or []:
        if not isinstance(year, dict):
            continue
        sems = next((v for k, v in year.items() if isinstance(v, list)), [])
        for sem in sems:
            subjects = next((v for k, v in sem.items() if "subjects" in k), "") if isinstance(sem, dict) else ""
            counts.append(len(re.findall(r"<li\b", str(subjects or ""), re.I)) or len([s for s in re.split(r"\n|<br\s*/?>", str(subjects or "")) if plain(s)]))
    return counts


def _all_text(value: Any) -> str:
    """Every string in a value, all rows included."""
    if isinstance(value, list):
        return " ".join(_all_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_all_text(v) for v in value.values())
    return plain(value)


def run_check(check: dict[str, Any], acf: dict[str, Any], title: str | None) -> dict[str, Any]:
    field = check.get("field")
    value = title if field == "post_title" else acf.get(field)
    kind = check["type"]
    if kind == "equals":
        ok = short_score(value, check["value"]) >= SHORT_PASS
        got = plain(value)
    elif kind == "row_count":
        got = len(value) if isinstance(value, list) else 0
        ok = got == check["equals"]
    elif kind == "semester_subjects":
        got = _subject_counts(value)
        ok = got == check["equals"]
    elif kind == "contains":
        text = norm(_all_text(value))
        missing = [p for p in check["phrases"] if norm(p) not in text]
        ok, got = not missing, (f"missing: {missing}" if missing else "all present")
    elif kind == "not_contains":
        text = norm(_all_text(value))
        present = [p for p in check["phrases"] if norm(p) in text]
        ok, got = not present, (f"present: {present}" if present else "none present")
    elif kind == "empty":
        ok, got = empty(value), plain(value)[:80]
    elif kind == "not_empty":
        ok, got = not empty(value), plain(value)[:80]
    elif kind == "html_list_items":
        got = len(re.findall(r"<li\b", str(value or ""), re.I))
        ok = got == check["equals"]
    else:
        raise ValueError(f"unknown check type {kind!r}")
    return {"check": check, "passed": bool(ok), "got": got, "category": check.get("category") or category(field or "")}


# ── truth-free invariants (what would show on the page) ───────────────

def invariants(acf: dict[str, Any], page_type: str, markdown: str, title: str, tables: list,
               generated: list[str] | None = None) -> list[dict[str, Any]]:
    """The checks v2 itself runs, applied to the projected page, plus placeholders."""
    out = []
    for f in check_payload(acf, page_type, markdown, title, tables, generated=generated or ()):
        if f["severity"] == "info":
            continue
        out.append({**f, "category": CHECK_CATEGORIES.get(f["code"], "other")})
    for key, value in acf.items():
        if isinstance(value, str) and _PLACEHOLDER_RE.match(value):
            out.append({"field_key": key, "code": "placeholder", "severity": "error",
                        "message": f"Placeholder {value!r} would be shown.", "category": "placeholders"})
    return out
