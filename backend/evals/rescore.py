"""Re-check a finished eval run's saved outputs with the current checks and truth.

    cd backend
    python -m evals.rescore evals/reports/<run> --out evals/reports/<run>-rescored

No pipeline runs and no API calls: the projected WordPress bodies saved in
results.json are scored again against each case's current checks, page
checks and truth. Use it after changing checks or truth (v1 can't be
replayed from the response cache: its SEO request depends on call order).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evals import scoring
from evals.cases import load_cases
from evals.report import agreement, build


def rescore(results: dict[str, Any], cases_dir: Path | None = None) -> dict[str, Any]:
    from pipeline.v2.markdown import to_markdown

    cases = {c.case_id: c for c in (load_cases(cases_dir) if cases_dir else load_cases())}
    docs: dict[str, Any] = {}
    for variant in results["variants"].values():
        for result in variant["cases"]:
            case = cases.get(result["case_id"])
            if case is None or result.get("acf") is None:
                continue
            if case.case_id not in docs:
                docs[case.case_id] = to_markdown(case.doc_bytes(), case.filename)
            md = docs[case.case_id]
            acf, title = result["acf"], result.get("title")
            truth = case.truth()
            result["fields"] = scoring.score_case(acf, truth["acf"], title, truth.get("title"), set(case.ignore_fields)) if truth else []
            result["checks"] = [scoring.run_check(c, acf, title) for c in case.checks]
            result["invariants"] = scoring.invariants(acf, case.page_type, md.markdown, case.filename.rsplit(".", 1)[0],
                                                      md.tables, result.get("generated"))
    results["agreement_opus_sonnet"] = agreement(results["variants"], "v2-opus/raw", "v2-sonnet/raw")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    results = rescore(json.loads((args.run / "results.json").read_text(encoding="utf-8")))
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    (args.out / "report.md").write_text(build(results), encoding="utf-8")
    print(f"re-scored {len(results['cases'])} cases -> {args.out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
