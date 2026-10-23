"""Run one pipeline on one document, without the app's database or network
side effects other than the (cached, budget-capped) model calls.

v1 runs the real run_extraction_pipeline against a throwaway in-memory
SQLite session, with its Anthropic and OpenAI clients swapped for the
caching ones. v2 runs pipeline.v2.run.run_v2 with the caching client.
"""

from __future__ import annotations

import os
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from evals.clients import CachingAnthropic, CachingOpenAI, Ledger, ResponseCache

PIPELINES: dict[str, dict[str, Any]] = {
    "v1": {"kind": "v1"},
    "v2-sonnet": {"kind": "v2", "model": "claude-sonnet-5-5"},
}


@dataclass
class Run:
    pipeline: str
    case_id: str
    payload: dict[str, Any] | None
    latency_ms: float
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@contextmanager
def _env(**values: str | None):
    saved = {k: os.environ.get(k) for k in values}
    for k, v in values.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _real_anthropic():
    import anthropic
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3)


def _real_openai():
    from openai import OpenAI
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"])


class Clients:
    def __init__(self, cache: ResponseCache, ledger: Ledger, anthropic_factory=_real_anthropic,
                 openai_factory=_real_openai) -> None:
        self.ledger = ledger
        self.anthropic = CachingAnthropic(anthropic_factory, cache, ledger)
        self.openai = CachingOpenAI(openai_factory, cache, ledger)


@contextmanager
def _v1_clients(clients: Clients):
    from pipeline import embedder, extractor

    saved = (extractor._anthropic, embedder._client, embedder._initialized, dict(embedder._field_index))
    extractor._anthropic = clients.anthropic
    embedder._client = clients.openai
    try:
        yield
    finally:
        extractor._anthropic, embedder._client, embedder._initialized = saved[0], saved[1], saved[2]
        embedder._field_index.clear()
        embedder._field_index.update(saved[3])


def _memory_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from db.database import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def run_v1(case_id: str, file_bytes: bytes, filename: str, page_type: str, clients: Clients) -> Run:
    from pipeline.service import run_extraction_pipeline

    engine, db = _memory_session()
    clients.ledger.blocked = None
    t0 = time.perf_counter()
    try:
        with clients.ledger.scoped("v1", case_id), _v1_clients(clients), _env(EXTRACTION_PIPELINE="v1"):
            result = run_extraction_pipeline(file_bytes, filename, page_type, db)
        if clients.ledger.blocked:  # v1 turned the refused call into a missing field
            return Run("v1", case_id, None, round((time.perf_counter() - t0) * 1000, 1), error=clients.ledger.blocked)
        return Run("v1", case_id, result["payload"], round((time.perf_counter() - t0) * 1000, 1),
                   meta={"quality_score": result["validation"]["summary"]["quality_score"]})
    except Exception as exc:
        return Run("v1", case_id, None, round((time.perf_counter() - t0) * 1000, 1),
                   error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")
    finally:
        db.close()
        engine.dispose()


def run_v2(pipeline: str, case_id: str, file_bytes: bytes, filename: str, page_type: str, clients: Clients,
           effort: str | None = None) -> Run:
    from pipeline.formatter import build_json_output
    from pipeline.v2.run import extra_report_fields, run_v2 as _run_v2

    model = PIPELINES[pipeline]["model"]
    clients.ledger.blocked = None
    t0 = time.perf_counter()
    try:
        with clients.ledger.scoped(pipeline, case_id), _env(V2_MODEL=model, V2_EFFORT=effort or os.getenv("V2_EFFORT") or "high"):
            result = _run_v2(file_bytes, filename, page_type, client=clients.anthropic)
        if clients.ledger.blocked:  # e.g. the SEO call was refused and turned into a flag
            return Run(pipeline, case_id, None, round((time.perf_counter() - t0) * 1000, 1), error=clients.ledger.blocked)
        final = build_json_output([{"field_key": k, "value": v} for k, v in result.payload.items()], filename, page_type)
        final["_meta"].update({"extraction": result.meta, "validation_flags": result.flags,
                               "extra_fields": extra_report_fields(page_type)})
        return Run(pipeline, case_id, final, round((time.perf_counter() - t0) * 1000, 1), meta=result.meta)
    except Exception as exc:
        return Run(pipeline, case_id, None, round((time.perf_counter() - t0) * 1000, 1),
                   error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")


def run_pipeline(pipeline: str, case_id: str, file_bytes: bytes, filename: str, page_type: str,
                 clients: Clients, effort: str | None = None) -> Run:
    if PIPELINES[pipeline]["kind"] == "v1":
        return run_v1(case_id, file_bytes, filename, page_type, clients)
    return run_v2(pipeline, case_id, file_bytes, filename, page_type, clients, effort)
