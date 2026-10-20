"""History/stats endpoints and the no-blocking rule for request handlers.

The deployed app froze for every user while one request ran: handlers were
declared ``async def`` but did blocking database/network work, which stalls
the event loop. A trivial /health call took 7s while /history?limit=500
was running. These tests keep that from coming back and pin the cheaper,
server-side-filtered history list the frontend now depends on.
"""

from __future__ import annotations

import inspect
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from catalog import service
from db.database import Base, get_db
from db.models import Upload
from main import app

pytestmark = pytest.mark.allow_httpx


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/history.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    service.migrate(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def api(factory):
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    yield TestClient(app)  # not a context manager: no startup/network
    app.dependency_overrides.clear()


def add(factory, filename, page_type="university", status="processed", minutes_ago=0):
    with factory() as db:
        u = Upload(filename=filename, page_type=page_type, status=status,
                   payload=json.dumps({"_meta": {}, "university_name": filename}),
                   created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
        db.add(u)
        db.commit()
        return u.id


def test_request_handlers_never_block_the_event_loop():
    """Handlers doing blocking work must be plain ``def`` (FastAPI runs those
    in a worker thread). Only trivially cheap handlers may be ``async``."""
    allowed_async = {"/health"}
    offenders = [
        route.path for route in app.routes
        if isinstance(route, APIRoute)
        and route.endpoint.__module__ in ("main", "catalog.routes")
        and route.path not in allowed_async
        and inspect.iscoroutinefunction(route.endpoint)
    ]
    assert offenders == []


def test_history_search_and_type_filter_run_on_the_server(api, factory):
    add(factory, "Sharda Online MBA.docx", "course", minutes_ago=3)
    add(factory, "Sharda University Page.docx", "university", minutes_ago=2)
    add(factory, "UPES Marketing.docx", "specialization", minutes_ago=1)

    body = api.get("/history", params={"q": "sharda"}).json()
    assert body["total"] == 2
    assert [u["filename"] for u in body["uploads"]] == ["Sharda University Page.docx", "Sharda Online MBA.docx"]

    body = api.get("/history", params={"q": "sharda", "page_type": "course"}).json()
    assert body["total"] == 1 and body["uploads"][0]["page_type"] == "course"

    body = api.get("/history", params={"page_type": "all"}).json()
    assert body["total"] == 3


def test_history_total_counts_everything_not_just_the_page(api, factory):
    for i in range(7):
        add(factory, f"doc-{i}.docx", minutes_ago=i)
    body = api.get("/history", params={"limit": 3, "offset": 3}).json()
    assert body["total"] == 7
    assert [u["filename"] for u in body["uploads"]] == ["doc-3.docx", "doc-4.docx", "doc-5.docx"]


def test_stats_counts_by_status_in_one_call(api, factory):
    add(factory, "a.docx", status="published")
    add(factory, "b.docx", status="draft_published")
    add(factory, "c.docx", status="processed")
    add(factory, "d.docx", status="processed")
    body = api.get("/stats").json()
    assert body["total"] == 4
    assert body["by_status"] == {"published": 1, "draft_published": 1, "processed": 2}
    assert body["last_upload_at"]


def test_stats_on_an_empty_database(api):
    assert api.get("/stats").json() == {"total": 0, "by_status": {}, "last_upload_at": None}


def test_legacy_live_page_is_flagged_without_parsing_its_payload(api, factory, monkeypatch):
    monkeypatch.setenv("WORDPRESS_SITE_URL", "https://degreebaba.com")
    monkeypatch.setenv("CHATBOT_BASE_URL", "https://chatbot.test")
    monkeypatch.setenv("CHATBOT_CATALOG_WEBHOOK_SECRET", "test-shared-secret-never-production-12345")
    live = add(factory, "live.docx", status="published")
    draft = add(factory, "draft.docx", status="draft_published")
    rows = {u["id"]: u["catalog_sync"] for u in api.get("/history").json()["uploads"]}
    assert rows[live]["status"] == "failed" and "Legacy publication" in rows[live]["last_error"]
    assert rows[draft]["status"] == "not eligible/draft"
