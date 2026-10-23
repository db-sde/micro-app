"""Merge several eval runs (e.g. parallel batches) into one report.

    cd backend
    python -m evals.merge evals/reports/<run1> evals/reports/<run2> ... --out evals/reports/<name>

Writes results.json and report.md for the combined set of cases. A case
present in several runs keeps the latest run's results.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from evals.report import agreement, build


def merge(runs: list[dict[str, Any]]) -> dict[str, Any]:
    variants: dict[str, dict[str, Any]] = {}
    case_order: list[str] = []
    for run in sorted(runs, key=lambda r: r["started_at"]):
        for name, data in run["variants"].items():
            slot = variants.setdefault(name, {"cases": []})
            for case in data["cases"]:
                slot["cases"] = [c for c in slot["cases"] if c["case_id"] != case["case_id"]] + [case]
                if case["case_id"] not in case_order:
                    case_order.append(case["case_id"])
    for slot in variants.values():
        slot["cases"].sort(key=lambda c: case_order.index(c["case_id"]))
    return {
        "started_at": " + ".join(sorted({r["started_at"] for r in runs})),
        "cases": case_order,
        "split": "all",
        "pipelines": sorted({p for r in runs for p in r["pipelines"]}),
        "prompt_version": " / ".join(sorted({r["prompt_version"] for r in runs})),
        "effort": runs[0].get("effort"),
        "spent_usd": round(sum(r["spent_usd"] for r in runs), 4),
        "cache_hits": sum(r["cache_hits"] for r in runs),
        "cache_misses": sum(r["cache_misses"] for r in runs),
        "stopped": "; ".join(r["stopped"] for r in runs if r.get("stopped")) or None,
        "variants": variants,
        "agreement_opus_sonnet": agreement(variants, "v2-opus/raw", "v2-sonnet/raw"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    merged = merge([json.loads((r / "results.json").read_text(encoding="utf-8")) for r in args.runs])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "results.json").write_text(json.dumps(merged, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    text = build(merged)
    if merged["stopped"]:
        text = f"> **Some runs stopped early:** {merged['stopped']}\n\n" + text
    (args.out / "report.md").write_text(text, encoding="utf-8")
    print(f"{len(merged['cases'])} cases -> {args.out / 'report.md'} (spent ${merged['spent_usd']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
