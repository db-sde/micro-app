"""Run v1 and v2 on every eval case and write the comparison report.

    cd backend
    python -m evals.run_eval --estimate-only                 # cost estimate, no calls
    python -m evals.run_eval --offline                       # cache only, never calls an API
    python -m evals.run_eval --yes --budget 30               # allowed to spend up to $30
    python -m evals.run_eval --pipelines v2-sonnet --cases jamia-mba --split dev --yes

Safety: refuses to run with ANTHROPIC_BASE_URL or chatbot settings in the
environment; the app database is an in-memory SQLite; WordPress is only
ever the in-memory fake (evals.projection). Uncached model calls need
--yes, and stop at --budget.
"""

from __future__ import annotations

import os
import sys

# Before any app module loads .env: never the real database.
os.environ["DATABASE_URL"] = "sqlite://"

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
DEFAULT_CACHE = EVALS_DIR / ".cache" / "responses"
DEFAULT_REPORTS = EVALS_DIR / "reports"

MODES = {"v1": ("published", "raw"), "v2-sonnet": ("raw", "published")}


def safety_problems(env: dict[str, str]) -> list[str]:
    problems = []
    if env.get("ANTHROPIC_BASE_URL"):
        problems.append("ANTHROPIC_BASE_URL is set; unset it so the API key only goes to api.anthropic.com "
                        "(run with: env -u ANTHROPIC_BASE_URL python -m evals.run_eval ...).")
    for key in ("CHATBOT_BASE_URL", "CHATBOT_CATALOG_WEBHOOK_SECRET"):
        if env.get(key):
            problems.append(f"{key} is set; chatbot sync must stay disabled in this copy.")
    return problems


def evaluate_case(case, pipelines: list[str], clients, effort: str | None) -> dict[str, dict[str, Any]]:
    """-> {"<pipeline>/<mode>": case result} for one case."""
    from evals import scoring
    from evals.projection import project
    from evals.runners import run_pipeline
    from pipeline.v2.markdown import to_markdown

    doc_bytes = case.doc_bytes()
    md = to_markdown(doc_bytes, case.filename)
    truth = case.truth()
    title = case.filename.rsplit(".", 1)[0]
    out: dict[str, dict[str, Any]] = {}
    for pipeline in pipelines:
        run = run_pipeline(pipeline, case.case_id, doc_bytes, case.filename, case.page_type, clients, effort)
        ledger_run = clients.ledger.runs.get((pipeline, case.case_id), {})
        for mode in MODES[pipeline]:
            result: dict[str, Any] = {
                "case_id": case.case_id, "pipeline": pipeline, "mode": mode, "error": run.error,
                "latency_ms": run.latency_ms, "cost_usd": ledger_run.get("cost_usd", 0.0),
                "usage": ledger_run.get("usage", {}), "calls": ledger_run.get("calls", 0),
                "fields": [], "checks": [], "invariants": [], "title": None,
                "notes": (run.meta or {}).get("notes") or [],
                "generated": (run.meta or {}).get("generated") or [],
            }
            if run.payload is not None:
                projected = project(run.payload, case.page_type, mode)
                result["title"] = projected["title"]
                result["acf"] = projected["acf"]
                if truth:
                    result["fields"] = scoring.score_case(projected["acf"], truth["acf"], projected["title"],
                                                          truth.get("title"), set(case.ignore_fields))
                result["checks"] = [scoring.run_check(c, projected["acf"], projected["title"]) for c in case.checks]
                result["invariants"] = scoring.invariants(projected["acf"], case.page_type, md.markdown, title, md.tables,
                                                          (run.meta or {}).get("generated"))
            out[f"{pipeline}/{mode}"] = result
    return out


def main(argv: list[str] | None = None, anthropic_factory=None, openai_factory=None, env: dict[str, str] | None = None,
         cases_dir: Path | None = None, cache_dir: Path = DEFAULT_CACHE, reports_dir: Path = DEFAULT_REPORTS) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", nargs="*", help="case ids (default: all)")
    parser.add_argument("--split", default="all", choices=("all", "dev", "holdout"))
    parser.add_argument("--pipelines", default="v1,v2-sonnet")
    parser.add_argument("--effort", default=None, help="v2 effort (default V2_EFFORT or high)")
    parser.add_argument("--offline", action="store_true", help="use cached responses only; never call an API")
    parser.add_argument("--yes", action="store_true", help="allow uncached (paid) calls after the estimate")
    parser.add_argument("--budget", type=float, default=25.0, help="stop before spending more than this (USD)")
    parser.add_argument("--estimate-only", action="store_true")
    args = parser.parse_args(argv)

    problems = safety_problems(dict(os.environ) if env is None else env)
    if problems:
        for p in problems:
            print(f"REFUSED: {p}", file=sys.stderr)
        return 3

    from evals import estimate as est
    from evals import report
    from evals.cases import CASES_DIR, load_cases
    from evals.clients import BudgetExceeded, Ledger, OfflineMiss, ResponseCache
    from evals.runners import PIPELINES, Clients
    from pipeline.v2.extract import PROMPT_VERSION
    from pipeline.v2.markdown import to_markdown

    logging.getLogger("degreebaba.wordpress").setLevel(logging.ERROR)
    pipelines = [p.strip() for p in args.pipelines.split(",") if p.strip()]
    unknown = [p for p in pipelines if p not in PIPELINES]
    if unknown:
        parser.error(f"unknown pipeline(s) {unknown}; choose from {list(PIPELINES)}")
    cases = load_cases(cases_dir or CASES_DIR, args.cases, args.split)
    if not cases:
        print(f"No eval cases in {cases_dir or CASES_DIR}. Add one with evals/README.md.", file=sys.stderr)
        return 1

    cache = ResponseCache(cache_dir)
    effort = args.effort or os.getenv("V2_EFFORT") or "high"
    estimates = []
    for case in cases:
        md = to_markdown(case.doc_bytes(), case.filename)
        for p in pipelines:
            if PIPELINES[p]["kind"] == "v1":
                estimates.append(est.estimate_v1(case.case_id, case.doc_bytes()))
            else:
                estimates.append(est.estimate_v2(case.case_id, p, md.markdown, case.page_type,
                                                 case.filename.rsplit(".", 1)[0], effort, cache))
    print("Estimated cost of uncached calls:\n")
    print(est.table(estimates) + "\n")
    expected = sum(e.usd for e in estimates)
    if args.estimate_only:
        return 0
    if not args.offline and expected > 0 and not args.yes:
        print("Nothing was run. Re-run with --yes to allow these calls (or --offline for cached results only).")
        return 2

    ledger = Ledger(budget_usd=args.budget, offline=args.offline)
    factories = {}
    if anthropic_factory:
        factories["anthropic_factory"] = anthropic_factory
    if openai_factory:
        factories["openai_factory"] = openai_factory
    clients = Clients(cache, ledger, **factories)

    started = time.strftime("%Y-%m-%d %H:%M")
    variants: dict[str, dict[str, Any]] = {}
    stopped = None
    for case in cases:
        try:
            per_case = evaluate_case(case, pipelines, clients, effort)
        except (BudgetExceeded, OfflineMiss) as exc:
            stopped = f"{case.case_id}: {exc}"
            break
        for name, result in per_case.items():
            variants.setdefault(name, {"cases": []})["cases"].append(result)
            if isinstance(result.get("error"), str) and ("BudgetExceeded" in result["error"] or "OfflineMiss" in result["error"]):
                stopped = stopped or f"{case.case_id}: {result['error'].splitlines()[0]}"
        print(f"{case.case_id}: done (spent so far ${ledger.spent_usd:.2f})")

    from evals.report import agreement
    agreement_result = agreement(variants, "v2-opus/raw", "v2-sonnet/raw")
    results = {"agreement_opus_sonnet": agreement_result, "started_at": started, "cases": [c.case_id for c in cases], "split": args.split,
               "pipelines": pipelines, "prompt_version": PROMPT_VERSION, "effort": effort,
               "spent_usd": round(ledger.spent_usd, 4), "cache_hits": ledger.cache_hits,
               "cache_misses": ledger.cache_misses, "stopped": stopped, "variants": variants}
    out_dir = reports_dir / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    text = report.build(results)
    if stopped:
        text = f"> **Run stopped early:** {stopped}\n\n" + text
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    print(f"\nReport: {out_dir / 'report.md'}\nSpent: ${ledger.spent_usd:.2f}")
    return 0 if not stopped else 4


if __name__ == "__main__":
    sys.exit(main())
