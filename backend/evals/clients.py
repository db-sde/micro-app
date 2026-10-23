"""Recording, caching, budget-capped stand-ins for the API clients.

Every real response is stored on disk keyed by the exact request, so a
re-run with the same prompt and document costs nothing, and changes to
scoring, checks or derivations never re-spend. A request that isn't
cached is only sent when the run allows it (not --offline) and the
running spend stays under the budget.

Costs are tracked twice: `spent_usd` (real calls made now) and the
nominal cost of each run (what the call costs, cached or not), which is
what the report compares.
"""

from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

# USD per million tokens: input, output, cache read, cache write.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20, 2.50),
    "claude-haiku-4-5-20251001": (1.00, 5.00, 0.10, 1.25),
    "claude-haiku-4-5": (1.00, 5.00, 0.10, 1.25),
    "text-embedding-3-large": (0.13, 0.0, 0.0, 0.0),
}


class OfflineMiss(RuntimeError):
    """A call was needed but the run is cache-only."""


class BudgetExceeded(RuntimeError):
    """The next real call would take spend past --budget."""


def price(model: str, usage: dict[str, int]) -> float:
    p_in, p_out, p_read, p_write = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (usage.get("input_tokens", 0) * p_in + usage.get("output_tokens", 0) * p_out
            + usage.get("cache_read_input_tokens", 0) * p_read
            + usage.get("cache_creation_input_tokens", 0) * p_write) / 1_000_000


class Ledger:
    """Spend and usage, per (pipeline, case) scope."""

    def __init__(self, budget_usd: float | None = None, offline: bool = False) -> None:
        self.budget_usd = budget_usd
        self.offline = offline
        self.spent_usd = 0.0
        self.scope: tuple[str, str] = ("", "")
        self.runs: dict[tuple[str, str], dict[str, Any]] = {}
        self.cache_hits = 0
        self.cache_misses = 0
        self._lock = threading.Lock()  # v1 calls the model from a thread pool
        # Set when a call was refused. v1 swallows per-field errors, so runners
        # check this instead of trusting a payload with silently-missing fields.
        self.blocked: str | None = None

    @contextmanager
    def scoped(self, pipeline: str, case: str):
        previous, self.scope = self.scope, (pipeline, case)
        self.runs.setdefault(self.scope, {"calls": 0, "cached_calls": 0, "cost_usd": 0.0, "usage": {}})
        try:
            yield self.runs[self.scope]
        finally:
            self.scope = previous

    def before_real_call(self, estimate_usd: float = 0.0) -> None:
        with self._lock:
            self._check_allowed(estimate_usd)

    def _check_allowed(self, estimate_usd: float) -> None:
        if self.offline:
            self.blocked = "OfflineMiss: not in the response cache and the run is --offline."
            raise OfflineMiss(self.blocked)
        if self.budget_usd is not None and self.spent_usd + estimate_usd > self.budget_usd:
            self.blocked = f"BudgetExceeded: budget ${self.budget_usd:.2f} reached (spent ${self.spent_usd:.2f})."
            raise BudgetExceeded(self.blocked)

    def record(self, model: str, usage: dict[str, int], cached: bool) -> None:
        with self._lock:
            self._record(model, usage, cached)

    def _record(self, model: str, usage: dict[str, int], cached: bool) -> None:
        cost = price(model, usage)
        run = self.runs.setdefault(self.scope, {"calls": 0, "cached_calls": 0, "cost_usd": 0.0, "usage": {}})
        run["calls"] += 1
        run["cached_calls"] += int(cached)
        run["cost_usd"] = round(run["cost_usd"] + cost, 6)
        for k, v in usage.items():
            run["usage"][k] = run["usage"].get(k, 0) + v
        if cached:
            self.cache_hits += 1
        else:
            self.cache_misses += 1
            self.spent_usd += cost


class ResponseCache:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def key(kind: str, request: dict[str, Any]) -> str:
        blob = json.dumps({"kind": kind, "request": request}, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path(self, key: str) -> Path:
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def put(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


# ── Anthropic ──────────────────────────────────────────────────────────

def _usage_of(message: Any) -> dict[str, int]:
    usage = getattr(message, "usage", None)
    return {k: int(getattr(usage, k, 0) or 0) for k in
            ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}


def _store_message(message: Any) -> dict[str, Any]:
    blocks = []
    for b in getattr(message, "content", None) or []:
        entry = {"type": getattr(b, "type", None)}
        if entry["type"] == "text":
            entry["text"] = b.text
        blocks.append(entry)
    details = getattr(message, "stop_details", None)
    return {"content": blocks, "stop_reason": getattr(message, "stop_reason", None),
            "stop_details": {"category": getattr(details, "category", None)} if details else None,
            "model": getattr(message, "model", None), "usage": _usage_of(message)}


def _load_message(stored: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(**b) for b in stored["content"]],
        stop_reason=stored["stop_reason"],
        stop_details=SimpleNamespace(**stored["stop_details"]) if stored.get("stop_details") else None,
        model=stored["model"], usage=SimpleNamespace(**stored["usage"]),
    )


class _Stream:
    def __init__(self, get: Callable[[], SimpleNamespace]):
        self._get = get

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._get()


class CachingAnthropic:
    """Duck-types the parts of anthropic.Anthropic both pipelines use:
    v2's beta.messages.stream(...) and v1's messages.create(...)."""

    def __init__(self, real_factory: Callable[[], Any], cache: ResponseCache, ledger: Ledger) -> None:
        self._real_factory = real_factory
        self._real = None
        self.cache = cache
        self.ledger = ledger
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self.messages = SimpleNamespace(create=self._create)

    def _client(self):
        if self._real is None:
            self._real = self._real_factory()
        return self._real

    def _call(self, kind: str, kwargs: dict[str, Any], send: Callable[[], Any]) -> SimpleNamespace:
        key = self.cache.key(kind, kwargs)
        stored = self.cache.get(key)
        cached = stored is not None
        if not cached:
            self.ledger.before_real_call()
            stored = _store_message(send())
            self.cache.put(key, stored)
        self.ledger.record(kwargs.get("model", ""), stored["usage"], cached)
        return _load_message(stored)

    def _stream(self, **kwargs):
        def send():
            with self._client().beta.messages.stream(**kwargs) as stream:
                return stream.get_final_message()
        return _Stream(lambda: self._call("beta.messages.stream", kwargs, send))

    def _create(self, **kwargs):
        return self._call("messages.create", kwargs, lambda: self._client().messages.create(**kwargs))


# ── OpenAI embeddings (v1) ─────────────────────────────────────────────

class CachingOpenAI:
    def __init__(self, real_factory: Callable[[], Any], cache: ResponseCache, ledger: Ledger) -> None:
        self._real_factory = real_factory
        self._real = None
        self.cache = cache
        self.ledger = ledger
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        key = self.cache.key("embeddings.create", kwargs)
        stored = self.cache.get(key)
        cached = stored is not None
        if not cached:
            self.ledger.before_real_call()
            if self._real is None:
                self._real = self._real_factory()
            response = self._real.embeddings.create(**kwargs)
            stored = {"data": [list(d.embedding) for d in response.data],
                      "prompt_tokens": int(getattr(response.usage, "prompt_tokens", 0) or 0)}
            self.cache.put(key, stored)
        self.ledger.record(kwargs.get("model", "text-embedding-3-large"), {"input_tokens": stored["prompt_tokens"]}, cached)
        return SimpleNamespace(data=[SimpleNamespace(embedding=e, index=i) for i, e in enumerate(stored["data"])],
                               usage=SimpleNamespace(prompt_tokens=stored["prompt_tokens"]))
