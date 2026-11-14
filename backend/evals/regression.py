"""Content-map regression: every rule in CONTENT_MAP.md, checked on every
eval document at once.

Each document is parsed with the current pipeline (v2, real model calls),
then sent through the real publish code against an in-memory WordPress
built from the committed staging schema (nothing reaches WordPress). The
ACF body it would send is checked against the rules below. A rule that
holds on 3 of 5 documents shows up here, not on review.

    cd backend && python -m evals.regression                 # all cases (~$0.10 per document)
    python -m evals.regression --cases upes-university jamia-mba
    python -m evals.regression --from-report reports/regression-…/payloads.json   # re-check, no model calls

Writes evals/reports/regression-<timestamp>/{report.md, results.json, payloads.json}.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from evals.cases import CASES_DIR, load_cases
from evals.projection import project

REPORTS = Path(__file__).resolve().parent / "reports"
NOT_GIVEN = re.compile(r"\bnot\s+(?:been\s+)?(?:mentioned|available|specified|applicable|offered|given|provided|stated)\b|\bn/a\b", re.I)
VALUE_FIELDS = ("program_validity", "certificate_validity", "emi_amount", "num_specializations", "nirf_rank", "nirf_rank_course",
                "duration", "total_fee", "starting_fee", "best_price_value", "best_price_specialization")
QUICK_FACT_LABELS = re.compile(r"\b(university full name|established year|starting fee|number of programs)\b", re.I)
STAT = re.compile(r"\d[\d,.]*\s*\+|\d+(?:\.\d+)?\s*(?:LPA|lakh|%)", re.I)


def plain(v: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(v or ""))).strip()


def items(html: Any) -> list[str]:
    return [plain(x) for x in re.findall(r"<li[^>]*>(.*?)</li>", str(html or ""), re.I | re.S) if plain(x)]


def key(name: str) -> str:
    from pipeline import wordpress_client as wc
    return wc._name_key(name)


# ── the rules (CONTENT_MAP.md) ─────────────────────────────────────────────
# Each: (page types, check(sent_acf, payload) -> None if fine, else a short reason)

def _names_once(chips_key: str, text_key: str) -> Callable:
    def check(acf, payload):
        names = {key(n) for n in items(acf.get(chips_key))} - {""}
        text = f" {key(plain(acf.get(text_key)))} "
        repeated = [n for n in names if f" {n} " in text]
        return f"{len(repeated)} names repeated: {repeated[:3]}" if len(repeated) >= 2 else None
    return check


def _partners_field(pt):
    return {"university": "placement_highlights", "course": "top_hiring_partners_course", "specialization": "hiring_partners_specialization"}[pt]


def _banks_field(pt):
    return {"university": "partner_banks_names", "course": "partner_banks_course", "specialization": "partner_banks_specialization"}[pt]


def partners_once(acf, payload, pt):
    return _names_once(_partners_field(pt), "placement_content")(acf, payload)


def banks_once(acf, payload, pt):
    return _names_once(_banks_field(pt), "emi_content")(acf, payload)


def partner_chips_are_companies(acf, payload, pt):
    from pipeline import wordpress_client as wc
    odd = [x for x in items(acf.get(_partners_field(pt))) if re.search(r"\d|%", x) or wc._SECTOR_WORDS.match(x) or x[:1].islower()]
    return f"not companies: {odd[:3]}" if odd else None


def placement_stats_kept(acf, payload, pt):
    before = set(STAT.findall(plain(payload.get("placement_content"))))
    lost = before - set(STAT.findall(plain(acf.get("placement_content"))))
    return f"lost {sorted(lost)}" if lost else None


def job_paragraph_once(acf, payload, pt):
    if pt != "specialization":
        return None
    a, b = plain(acf.get("jobs_content")), plain(acf.get("job_profiles_section_paragraph"))
    return "same paragraph in jobs_content and job_profiles_section_paragraph" if a and b and a == b else None


def eligibility_note_adds_something(acf, payload, pt):
    s = plain(acf.get("eligibility_summary")).lower()
    crit = [plain(r.get("eligibility_description")).lower() for r in acf.get("eligibility_content") or [] if isinstance(r, dict)]
    return "repeats a criterion" if s and any(c and (s in c or c in s) for c in crit) else None


def validity_not_copied(acf, payload, pt):
    v = plain(acf.get("program_validity")).lower()
    return f"validity == duration ({v})" if v and v == plain(acf.get("duration")).lower() else None


def no_not_given_values(acf, payload, pt):
    bad = {k: acf[k] for k in VALUE_FIELDS if isinstance(acf.get(k), str) and NOT_GIVEN.search(acf[k])}
    count = acf.get("num_specializations")
    if count is not None and str(count).strip() and not re.search(r"[1-9]", str(count)):
        bad["num_specializations"] = count
    return f"{bad}" if bad else None


def steps_are_a_list(acf, payload, pt):
    steps = acf.get("admission_steps")
    if not acf.get("admission_heading") and not steps:
        return None
    n = len(re.findall(r"<li", str(steps or ""), re.I))
    if n < 2:
        return f"{n} step(s)"
    return "more than one numbered list" if str(steps).lower().count("<ol") > 1 else None


def facts_are_not_quick_facts(acf, payload, pt):
    if pt != "university":
        return None
    hits = QUICK_FACT_LABELS.findall(plain(acf.get("facts_content")))
    return f"quick-facts labels in facts: {sorted(set(h.lower() for h in hits))}" if len(hits) >= 2 else None


def spec_name_has_program(acf, payload, pt):
    if pt != "specialization":
        return None
    return None if re.search(r"\bin\b", str(acf.get("spec_name") or ""), re.I) else f"name {acf.get('spec_name')!r}"


def other_specs_consistent(acf, payload, pt):
    if pt != "specialization":
        return None
    rows = acf.get("other_specs") or []
    fee = [r for r in rows if r.get("other_spec_fee")]
    nofee = [r.get("other_spec_name") for r in rows if not r.get("other_spec_fee")]
    return f"some with a fee, these without: {nofee[:3]}" if fee and nofee else None


def course_specs_are_specializations(acf, payload, pt):
    if pt != "course":
        return None
    names = [r.get("specialization_name") or "" for r in acf.get("specialization") or []]
    odd = [n for n in names if re.search(r"post\s*graduate diploma|\bdiploma\b|\bcertificate\b", n, re.I)]
    return f"programs listed as specializations: {odd[:3]}" if odd else None


RULES: list[tuple[str, Callable]] = [
    ("Hiring partners shown once", partners_once),
    ("Banks shown once", banks_once),
    ("Partner chips are companies", partner_chips_are_companies),
    ("Placement stats kept", placement_stats_kept),
    ("Job paragraph once (spec)", job_paragraph_once),
    ("Eligibility note not a copy", eligibility_note_adds_something),
    ("Validity not copied from duration", validity_not_copied),
    ("No 'not mentioned' values", no_not_given_values),
    ("Admission steps are one list", steps_are_a_list),
    ("Facts are not the Quick Facts block (uni)", facts_are_not_quick_facts),
    ("Spec name includes the program (spec)", spec_name_has_program),
    ("Other specs consistent (spec)", other_specs_consistent),
    ("Course specs are specializations", course_specs_are_specializations),
]


# ── running ────────────────────────────────────────────────────────────────

def parse_all(cases, workers: int = 4) -> dict[str, dict[str, Any]]:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import catalog.models  # noqa: F401
    import db.models  # noqa: F401
    from db.database import Base
    from pipeline.service import run_extraction_pipeline

    def one(case):
        eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(eng)
        with sessionmaker(bind=eng)() as s:
            t = time.time()
            try:
                resp = run_extraction_pipeline(case.doc_bytes(), case.filename, case.page_type, s)
                return case.case_id, {"page_type": case.page_type, "payload": resp["payload"], "secs": round(time.time() - t),
                                      "cost": (resp.get("extraction") or {}).get("cost_usd")}
            except Exception as exc:  # report it, keep going
                return case.case_id, {"page_type": case.page_type, "error": repr(exc)[:300]}

    with ThreadPoolExecutor(workers) as ex:
        return dict(ex.map(one, cases))


def check_all(parsed: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results = {}
    for case_id, item in parsed.items():
        if item.get("error"):
            results[case_id] = {"page_type": item["page_type"], "error": item["error"]}
            continue
        pt = item["page_type"]
        try:
            acf = project(json.loads(json.dumps(item["payload"])), pt)["acf"]
        except Exception as exc:
            results[case_id] = {"page_type": pt, "error": f"publish failed: {exc!r}"[:300]}
            continue
        results[case_id] = {"page_type": pt, "rules": {name: fn(acf, item["payload"], pt) for name, fn in RULES}}
    return results


def report(results: dict[str, Any], parsed: dict[str, Any]) -> str:
    lines = ["# Content-map regression", "", f"{len(results)} documents. ✅ = rule holds, ❌ = broken (reason below).", ""]
    lines += ["| Rule | Passed | Broken on |", "|---|---|---|"]
    for name, _ in RULES:
        ok = [c for c, r in results.items() if "rules" in r and r["rules"][name] is None]
        bad = [c for c, r in results.items() if "rules" in r and r["rules"][name] is not None]
        lines.append(f"| {name} | {len(ok)}/{len(ok) + len(bad)} | {', '.join(bad) or '—'} |")
    errors = {c: r["error"] for c, r in results.items() if "error" in r}
    if errors:
        lines += ["", "## Failed documents", ""] + [f"- {c}: {e}" for c, e in errors.items()]
    lines += ["", "## Details", ""]
    for c, r in results.items():
        broken = {k: v for k, v in (r.get("rules") or {}).items() if v}
        if broken:
            lines.append(f"- **{c}** ({r['page_type']}): " + "; ".join(f"{k}: {v}" for k, v in broken.items()))
    cost = sum((p.get("cost") or 0) for p in parsed.values())
    lines += ["", f"Model cost of this run: ${cost:.2f}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="*", help="case ids (default: all)")
    parser.add_argument("--from-report", help="payloads.json from an earlier run: re-check without model calls")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args(argv)
    logging.disable(logging.WARNING)
    if args.from_report:
        parsed = json.loads(Path(args.from_report).read_text())
    else:
        cases = load_cases(CASES_DIR, ids=args.cases)
        if not cases:
            print("No eval cases found under", CASES_DIR)
            return 2
        parsed = parse_all(cases, args.workers)
    results = check_all(parsed)
    out = REPORTS / f"regression-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "payloads.json").write_text(json.dumps(parsed, ensure_ascii=False))
    (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    text = report(results, parsed)
    (out / "report.md").write_text(text)
    print(text)
    print("Saved to", out)
    return 1 if any(("error" in r) or any(v for v in (r.get("rules") or {}).values()) for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
