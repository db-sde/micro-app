"""The Claude calls v2 makes: one streaming request with a JSON Schema
output, adaptive thinking and server-side refusal fallback; usage and
cost per call.

anthropic==0.105.2 has no typed `fallbacks` parameter, so it is sent via
`extra_body` with its beta header.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("degreebaba.v2.claude")

# Sonnet 5.5: on the 20-document eval it passed 99% of checks vs Opus 5.5's 100% at
# ~40% of the cost and half the time (2026-10-24). Opus stays available: V2_MODEL=claude-opus-5-5.
DEFAULT_MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: input, output, cache read, cache write (5-minute TTL).
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
}

_client = None


class ClaudeCallError(RuntimeError):
    """The call returned no usable JSON (refusal, truncation, bad JSON)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass
class CallResult:
    data: dict[str, Any]
    model: str                      # model requested
    served_by: str                  # model that produced the answer
    stop_reason: str | None
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    fallback_used: bool = False


def model_name() -> str:
    return os.getenv("V2_MODEL", "").strip() or DEFAULT_MODEL


def get_client():
    """Shared Anthropic client (thread-safe; credentials from the environment)."""
    global _client
    if _client is None:
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key.startswith("your_"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Please add it to .env.")
        _client = anthropic.Anthropic(api_key=api_key, max_retries=3)
    return _client


def cost_usd(model: str, usage: dict[str, int]) -> float:
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES[DEFAULT_MODEL])
    return round((usage.get("input_tokens", 0) * p_in + usage.get("output_tokens", 0) * p_out
                  + usage.get("cache_read_input_tokens", 0) * p_read
                  + usage.get("cache_creation_input_tokens", 0) * p_write) / 1_000_000, 4)


def _usage_dict(usage: Any) -> dict[str, int]:
    out = {}
    for key in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
        value = getattr(usage, key, None) if usage is not None else None
        out[key] = int(value or 0)
    return out


def _fallback_used(message: Any) -> bool:
    if any(getattr(b, "type", None) == "fallback" for b in (message.content or [])):
        return True
    iterations = getattr(getattr(message, "usage", None), "iterations", None) or []
    return any(getattr(i, "type", None) == "fallback_message" or (isinstance(i, dict) and i.get("type") == "fallback_message")
               for i in iterations)


def call_json(*, system: str, user: str, schema: dict[str, Any], model: str | None = None,
              effort: str = "high", max_tokens: int = 64000, client=None) -> CallResult:
    """One streaming request whose answer must match `schema`.

    Retries once with the 128K output cap if the answer was cut off.
    """
    model = model or model_name()
    client = client or get_client()
    caps = [max_tokens] if max_tokens >= 128000 else [max_tokens, 128000]
    total: dict[str, int] = {}
    t0 = time.perf_counter()
    for cap in caps:
        kwargs = dict(
            model=model,
            max_tokens=cap,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            extra_body={"fallbacks": "default"},
        )
        with client.beta.messages.stream(**kwargs) as stream:
            message = stream.get_final_message()
        usage = _usage_dict(getattr(message, "usage", None))
        for k, v in usage.items():
            total[k] = total.get(k, 0) + v
        stop = getattr(message, "stop_reason", None)
        logger.info("CLAUDE_CALL: model=%s served=%s stop=%s usage=%s", model, getattr(message, "model", model), stop, usage)
        if stop == "refusal":
            details = getattr(message, "stop_details", None)
            raise ClaudeCallError("refusal", f"The model declined the request ({getattr(details, 'category', None)}).")
        if stop == "max_tokens":
            continue
        text = "".join(getattr(b, "text", "") for b in (message.content or []) if getattr(b, "type", None) == "text")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ClaudeCallError("bad_json", f"The answer was not valid JSON: {exc}") from exc
        return CallResult(
            data=data, model=model, served_by=getattr(message, "model", None) or model, stop_reason=stop,
            usage=total, cost_usd=cost_usd(model, total), latency_ms=round((time.perf_counter() - t0) * 1000, 1),
            fallback_used=_fallback_used(message),
        )
    raise ClaudeCallError("max_tokens", f"The answer was cut off at the {caps[-1]:,}-token output limit.")
