"""Extraction v2 end to end, without persistence (pipeline/service.py saves it).

    docx -> Markdown -> one extraction call -> exact derivations ->
    SEO/hero texts -> checks -> payload + field_mappings + flags + meta
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from acf.fields import SKIP_EXTRACTION_FIELDS, get_v2_published_keys
from pipeline.v2 import checks, derive
from pipeline.v2.claude import ClaudeCallError, model_name
from pipeline.v2.extract import PROMPT_VERSION, extract
from pipeline.v2.generate import generate
from pipeline.v2.markdown import to_markdown
from pipeline.v2.schema import CONFIDENCE_SCORE, extracted_fields, field_defs, to_payload
from pipeline.validator import value_fingerprint

logger = logging.getLogger("degreebaba.v2")


@dataclass
class V2Result:
    page_type: str
    payload: dict[str, Any]
    mapping_records: list[dict[str, Any]]
    flags: list[dict[str, Any]]
    meta: dict[str, Any]


def document_title(filename: str) -> str:
    return re.sub(r"\.docx?$", "", (filename or "").strip(), flags=re.I)


def _detect_page_type(file_bytes: bytes) -> str:
    """The existing detector (one small model call), when the page type isn't given."""
    from pipeline.docx_parser import parse_docx
    from pipeline.page_detector import detect_page_type

    parsed = parse_docx(file_bytes)
    return detect_page_type(parsed.get("sections", parsed))


def _db_value(value: Any) -> Any:
    return value if value is None or isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def run_v2(file_bytes: bytes, filename: str, forced_page_type: str | None, client=None) -> V2Result:
    timings: dict[str, float] = {}
    t0 = time.perf_counter()

    doc = to_markdown(file_bytes, filename)
    timings["markdown_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    page_type = forced_page_type or _detect_page_type(file_bytes)
    title = document_title(filename)
    model = model_name()

    t1 = time.perf_counter()
    extraction = extract(doc.markdown, page_type, title, model=model, client=client)
    timings["extract_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    payload = to_payload(page_type, extraction.values)
    changes: list[dict[str, str]] = []
    changes += derive.null_placeholders(payload)
    changes += derive.apply_title_name(payload, page_type, filename)
    changes += derive.apply_specialization_fees(payload, doc.tables, page_type)
    changes += derive.apply_copies(payload, page_type)
    valid_keys = {f["key"] for f in field_defs(page_type)}
    changes += derive.apply_heading_fallbacks(payload, page_type, valid_keys, checks.is_usable_heading)

    for key, name in derive.relationship_hints(doc.markdown).items():
        if key in valid_keys and key in SKIP_EXTRACTION_FIELDS:
            payload[key] = name  # build_json_output moves this into _meta.relationship_hints

    t2 = time.perf_counter()
    calls = list(extraction.calls)
    flags: list[dict[str, Any]] = []
    generated: dict[str, str] = {}
    try:
        generated, gen_call = generate(payload, page_type, model=model, client=client)
        if gen_call:
            calls.append(gen_call)
        payload.update(generated)
    except ClaudeCallError as exc:
        flags.append(checks.flag("seo_title", "generation_failed", checks.WARNING, f"SEO/hero texts not written: {exc}"))
    timings["generate_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    flags += checks.check_payload(payload, page_type, doc.markdown, title, doc.tables, generated=generated)
    flags += checks.check_generated(payload, page_type, generated)
    for change in changes:
        flags.append(checks.flag(change["field_key"], "derived", checks.INFO, f"Set by rule: {change['rule']}"))
    if doc.parser != "docling":
        flags.append(checks.flag("_document", "parser_fallback", checks.WARNING,
                                 f"Docling failed ({doc.error}); the older parser was used."))
    for f in flags:
        f["value_fp"] = value_fingerprint(payload.get(f["field_key"]))

    records = _mapping_records(page_type, payload, extraction.provenance, changes, generated, flags)
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    meta = {
        "pipeline": "v2",
        "prompt_version": PROMPT_VERSION,
        "parser": doc.parser,
        "parser_error": doc.error,
        "model": model,
        "served_by": sorted({c.served_by for c in calls}),
        "fallback_used": any(c.fallback_used for c in calls),
        "calls": len(calls),
        "usage": _sum_usage(calls),
        "cost_usd": round(sum(c.cost_usd for c in calls), 4),
        "latency_ms": timings,
        "notes": extraction.notes,
        "generated": sorted(generated),
        "document_flags": [f for f in flags if f["field_key"] == "_document"],
    }
    logger.info("V2_DONE: file=%s type=%s cost=$%.4f usage=%s latency=%s flags=%d",
                filename, page_type, meta["cost_usd"], meta["usage"], timings, len(flags))
    return V2Result(page_type=page_type, payload=payload, mapping_records=records, flags=flags, meta=meta)


def _sum_usage(calls) -> dict[str, int]:
    total: dict[str, int] = {}
    for c in calls:
        for k, v in c.usage.items():
            total[k] = total.get(k, 0) + v
    return total


def _mapping_records(page_type, payload, provenance, changes, generated, flags) -> list[dict[str, Any]]:
    by_field: dict[str, list[dict[str, Any]]] = {}
    for f in flags:
        by_field.setdefault(f["field_key"], []).append(f)
    source = {p.get("field"): p for p in provenance if isinstance(p, dict)}
    records: list[dict[str, Any]] = []
    for f in extracted_fields(page_type):
        key = f["key"]
        if payload.get(key) is None:
            continue
        p = source.get(key) or {}
        base = CONFIDENCE_SCORE.get(p.get("confidence"), 0.5)
        records.append({
            "field_key": key,
            "heading_in_doc": ((p.get("heading") or "").strip() or "[LLM: no heading]")[:500],  # column limit
            "value": _db_value(payload[key]),
            "confidence": checks.adjusted_confidence(base, by_field.get(key, [])),
            "status": "mapped",
            "source": "LLM",
        })
    for change in changes:  # recorded after LLM rows: the screens show the last record per field
        key = change["field_key"]
        if payload.get(key) is None or change["rule"].startswith("placeholder"):
            continue
        records.append({
            "field_key": key, "heading_in_doc": f"[derived: {change['rule']}]", "value": _db_value(payload[key]),
            "confidence": checks.adjusted_confidence(0.95, by_field.get(key, [])), "status": "mapped", "source": "DERIVED",
        })
    for key in generated:
        records.append({
            "field_key": key, "heading_in_doc": "[AI Generated]", "value": _db_value(payload[key]),
            "confidence": checks.adjusted_confidence(1.0, by_field.get(key, [])), "status": "mapped", "source": "AI_GENERATED",
        })
    return records


def extra_report_fields(page_type: str) -> list[str]:
    """v2-only WordPress fields shown in the validation report."""
    return sorted(get_v2_published_keys(page_type))
