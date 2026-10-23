"""Comparison report (Markdown) from the run's results."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

PRIMARY = ("v1/published", "v2-opus/raw", "v2-sonnet/raw")  # get the detailed failure lists
ORDER = ("v1/published", "v1/raw", "v2-opus/raw", "v2-opus/published", "v2-sonnet/raw", "v2-sonnet/published")


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "–"


def variant_summary(variant: dict[str, Any]) -> dict[str, Any]:
    fields = [f for case in variant["cases"] for f in case["fields"] if not f["generated"] and f["status"] != "both_empty"]
    passed = sum(f["passed"] for f in fields)
    checks = [c for case in variant["cases"] for c in case["checks"]]
    inv = [i for case in variant["cases"] for i in case["invariants"]]
    runs = variant["cases"]
    return {
        "scored": len(fields), "passed": passed, "accuracy": passed / len(fields) if fields else None,
        "mean_score": sum(f["score"] for f in fields) / len(fields) if fields else None,
        "missed": sum(f["status"] == "missed" for f in fields), "invented": sum(f["status"] == "invented" for f in fields),
        "checks_passed": sum(c["passed"] for c in checks), "checks_total": len(checks),
        "invariant_errors": sum(i["severity"] == "error" for i in inv), "invariant_warnings": sum(i["severity"] == "warning" for i in inv),
        "errors": sum(1 for c in runs if c.get("error")),
        "cost_per_doc": sum(c["cost_usd"] for c in runs) / len(runs) if runs else 0.0,
        "latency_per_doc_s": sum(c["latency_ms"] for c in runs) / len(runs) / 1000 if runs else 0.0,
    }


def agreement(variants: dict[str, Any], a: str, b: str) -> dict[str, Any]:
    """Field-by-field agreement between two variants' pages (b scored against a), generated texts excluded."""
    from evals.scoring import GENERATED, NOT_SCORED_RE, category, empty, score_value, _snippet

    if a not in variants or b not in variants:
        return {}
    b_cases = {c["case_id"]: c for c in variants[b]["cases"]}
    total, agree, by_cat, diffs = 0, 0, defaultdict(lambda: [0, 0]), []
    for ca in variants[a]["cases"]:
        cb = b_cases.get(ca["case_id"])
        if not cb or ca.get("error") or cb.get("error"):
            continue
        acf_a, acf_b = ca.get("acf") or {}, cb.get("acf") or {}
        for key in sorted(set(acf_a) | set(acf_b)):
            if key in GENERATED or NOT_SCORED_RE.match(key):
                continue
            va, vb = acf_a.get(key), acf_b.get(key)
            if empty(va) and empty(vb):
                continue
            ok = score_value(vb, va)["passed"]
            total += 1
            agree += ok
            cat = category(key)
            by_cat[cat][0] += ok
            by_cat[cat][1] += 1
            if not ok:
                diffs.append({"case_id": ca["case_id"], "field": key, "category": cat, a: _snippet(va, 140), b: _snippet(vb, 140)})
    return {"total": total, "agree": agree, "by_category": dict(by_cat), "differences": diffs}


def build(results: dict[str, Any]) -> str:
    variants: dict[str, Any] = results["variants"]
    order = [v for v in ORDER if v in variants] + [v for v in variants if v not in ORDER]
    out = [f"# Extraction eval — {results['started_at']}", ""]
    out += [f"Cases: {', '.join(results['cases'])} ({results['split']}). Prompt {results['prompt_version']}. "
            f"Spent this run: ${results['spent_usd']:.2f} ({results['cache_hits']} cached calls, {results['cache_misses']} new).",
            "", "*raw* = the extraction as it comes out (publish-time repairs off); *published* = what /publish would send. "
            "Cost is per document at list price, cached calls included.", ""]

    out += ["## Summary", "", "variant | field accuracy | mean score | missed | invented | stress checks | page errors / warnings | failed runs | cost / doc | time / doc",
            "---|---|---|---|---|---|---|---|---|---"]
    summaries = {v: variant_summary(variants[v]) for v in order}
    for v in order:
        s = summaries[v]
        acc = f"{100 * s['accuracy']:.1f}% ({s['passed']}/{s['scored']})" if s["accuracy"] is not None else "– (no truth)"
        mean = f"{s['mean_score']:.3f}" if s["mean_score"] is not None else "–"
        out.append(f"{v} | {acc} | {mean} | {s['missed']} | {s['invented']} | {s['checks_passed']}/{s['checks_total']} | "
                   f"{s['invariant_errors']} / {s['invariant_warnings']} | {s['errors']} | ${s['cost_per_doc']:.3f} | {s['latency_per_doc_s']:.1f}s")

    # accuracy by category
    cats = sorted({f["category"] for v in order for c in variants[v]["cases"] for f in c["fields"] if not f["generated"]})
    if cats:
        out += ["", "## Accuracy by category", "", "category | " + " | ".join(order), "---|" + "---|" * len(order)]
        for cat in cats:
            row = []
            for v in order:
                fs = [f for c in variants[v]["cases"] for f in c["fields"] if f["category"] == cat and not f["generated"] and f["status"] != "both_empty"]
                row.append(f"{_pct(sum(f['passed'] for f in fs), len(fs))} ({sum(f['passed'] for f in fs)}/{len(fs)})" if fs else "–")
            out.append(f"{cat} | " + " | ".join(row))

    # fields that fail somewhere
    per_field: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    for v in order:
        for c in variants[v]["cases"]:
            for f in c["fields"]:
                if not f["generated"] and f["status"] != "both_empty":
                    per_field[f["field"]][v].append(f["passed"])
    failing = sorted(k for k, vs in per_field.items() if any(not all(x) for x in vs.values()))
    if failing:
        out += ["", "## Fields that failed in at least one variant", "", "field | " + " | ".join(order), "---|" + "---|" * len(order)]
        for k in failing:
            out.append(f"`{k}` | " + " | ".join(f"{sum(per_field[k][v])}/{len(per_field[k][v])}" if per_field[k][v] else "–" for v in order))

    # per document
    out += ["", "## Per document", "", "case | variant | accuracy | cost | time | input / output tokens | note", "---|---|---|---|---|---|---"]
    for v in order:
        for c in variants[v]["cases"]:
            fs = [f for f in c["fields"] if not f["generated"] and f["status"] != "both_empty"]
            usage = c.get("usage") or {}
            note = (c.get("error") or "").splitlines()[0][:80] if c.get("error") else ""
            out.append(f"{c['case_id']} | {v} | {_pct(sum(f['passed'] for f in fs), len(fs))} | ${c['cost_usd']:.3f} | "
                       f"{c['latency_ms'] / 1000:.1f}s | {usage.get('input_tokens', 0):,} / {usage.get('output_tokens', 0):,} | {note}")

    # stress checks
    rows = defaultdict(dict)
    for v in order:
        for c in variants[v]["cases"]:
            for chk in c["checks"]:
                label = f"{c['case_id']}: {chk['check']['type']} {chk['check'].get('field', '')}"
                rows[label][v] = ("✓" if chk["passed"] else "✗") + ("" if chk["passed"] else f" ({str(chk['got'])[:60]})")
    if rows:
        out += ["", "## Stress checks", "", "check | " + " | ".join(order), "---|" + "---|" * len(order)]
        for label in sorted(rows):
            out.append(f"{label} | " + " | ".join(rows[label].get(v, "–") for v in order))

    # Opus vs Sonnet: where they agree the field is very likely right; differences need a look
    agr = agreement(variants, "v2-opus/raw", "v2-sonnet/raw")
    if agr.get("total"):
        out += ["", "## Opus vs Sonnet agreement", "",
                f"Same value on **{agr['agree']}/{agr['total']}** non-empty fields ({_pct(agr['agree'], agr['total'])}). "
                "Generated SEO/hero texts are left out.", "", "category | agree", "---|---"]
        for cat, (ok, n) in sorted(agr["by_category"].items()):
            out.append(f"{cat} | {ok}/{n} ({_pct(ok, n)})")
        out += ["", f"**Differences ({len(agr['differences'])})**", ""]
        for d in agr["differences"][:80]:
            out.append(f"- **{d['case_id']}** `{d['field']}` — Opus: {d['v2-opus/raw']!r} — Sonnet: {d['v2-sonnet/raw']!r}")
        if len(agr["differences"]) > 80:
            out.append(f"- … {len(agr['differences']) - 80} more in results.json")

    # what the model said about each document (contradictions, content with no field)
    noted = [(c["case_id"], v, c["notes"]) for v in order if v.endswith("/raw") for c in variants[v]["cases"] if c.get("notes")]
    if noted:
        out += ["", "## Model notes", ""]
        for case_id, v, notes in noted:
            out += [f"**{case_id}** — {v.split('/')[0]}", "", *[f"- {n}" for n in notes], ""]

    # failures by category
    out += ["", "## Failures by category", ""]
    for v in [x for x in PRIMARY if x in variants]:
        by_cat: dict[str, list[str]] = defaultdict(list)
        for c in variants[v]["cases"]:
            for f in c["fields"]:
                if not f["passed"] and not f["generated"]:
                    by_cat[f["category"]].append(
                        f"- **{c['case_id']}** `{f['field']}` ({f['status']}, {f['score']:.2f}) — expected: {f['expected'][:120]!r} — got: {f['actual'][:120]!r}")
            for i in c["invariants"]:
                by_cat[i["category"]].append(f"- **{c['case_id']}** `{i['field_key']}` page check {i['code']} ({i['severity']}): {i['message'][:140]}")
        out += [f"### {v}", ""]
        if not by_cat:
            out += ["No failures.", ""]
        for cat in sorted(by_cat):
            items = by_cat[cat]
            out += [f"**{cat}** ({len(items)})", "", *items[:30], *([f"- … {len(items) - 30} more"] if len(items) > 30 else []), ""]
    return "\n".join(out) + "\n"
