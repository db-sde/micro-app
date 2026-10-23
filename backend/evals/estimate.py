"""Cost estimate before any paid run (no API calls; a ±60% range).

v2: input = system prompt + field schema + document (≈3.5 characters per
token); output = the document's content re-emitted as field values
(≈0.7× its tokens) + provenance + thinking. Plus the small SEO/hero call.
A v2 extraction already in the response cache costs nothing.

v1: one Haiku 4.5 call per document section (+ mapping confirmations and
the SEO call) at ≈1,200 input / 500 output tokens each; embeddings are
negligible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from evals.clients import ResponseCache, price
from evals.runners import PIPELINES

CHARS_PER_TOKEN = 3.5
THINKING_TOKENS = 10_000
PROVENANCE_TOKENS = 1_500
GENERATION = {"input_tokens": 1_800, "output_tokens": 1_500}
V1_CALL = {"input_tokens": 1_200, "output_tokens": 500}


@dataclass
class Estimate:
    case_id: str
    pipeline: str
    usd: float
    cached: bool
    detail: dict[str, Any]


def _v2_request(markdown: str, page_type: str, title: str, model: str, effort: str) -> dict[str, Any]:
    """The exact first extraction request run_v2 sends (to look it up in the cache)."""
    from pipeline.v2.claude import FALLBACK_BETA
    from pipeline.v2.extract import SYSTEM_PROMPT, user_message
    from pipeline.v2.schema import output_schema

    return dict(
        model=model, max_tokens=64000,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message(markdown, page_type, title)}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": output_schema(page_type)}},
        betas=[FALLBACK_BETA], extra_body={"fallbacks": "default"},
    )


def estimate_v2(case_id: str, pipeline: str, markdown: str, page_type: str, title: str, effort: str,
                cache: ResponseCache | None) -> Estimate:
    from pipeline.v2.extract import SYSTEM_PROMPT
    from pipeline.v2.schema import output_schema

    model = PIPELINES[pipeline]["model"]
    request = _v2_request(markdown, page_type, title, model, effort)
    cached = bool(cache and cache.get(cache.key("beta.messages.stream", request)))
    doc_tokens = len(markdown) / CHARS_PER_TOKEN
    usage = {
        "input_tokens": int((len(SYSTEM_PROMPT) + len(json.dumps(output_schema(page_type))) + len(markdown) + 200) / CHARS_PER_TOKEN),
        "output_tokens": int(doc_tokens * 0.7 + PROVENANCE_TOKENS + THINKING_TOKENS),
    }
    usd = 0.0 if cached else price(model, usage) + price(model, GENERATION)
    return Estimate(case_id, pipeline, round(usd, 4), cached, {"doc_tokens": int(doc_tokens), **usage})


def estimate_v1(case_id: str, file_bytes: bytes) -> Estimate:
    from pipeline.docx_parser import parse_docx

    sections = len(parse_docx(file_bytes).get("sections", {}))
    calls = int(sections * 1.3) + 1
    usage = {k: v * calls for k, v in V1_CALL.items()}
    return Estimate(case_id, "v1", round(price("claude-haiku-4-5-20251001", usage), 4), False,
                    {"sections": sections, "calls": calls, **usage})


def table(estimates: list[Estimate]) -> str:
    lines = ["case | pipeline | estimate (USD) | note", "---|---|---|---"]
    for e in estimates:
        note = "cached (free)" if e.cached else ", ".join(f"{k}={v:,}" for k, v in e.detail.items())
        lines.append(f"{e.case_id} | {e.pipeline} | {e.usd:.2f} | {note}")
    total = sum(e.usd for e in estimates)
    lines.append(f"**total** | | **{total:.2f}** (range {total * 0.6:.2f}–{total * 1.6:.2f}) |")
    return "\n".join(lines)
