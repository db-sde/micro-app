"""HTTP-contract smoke tests for the FastAPI app.

Scope is deliberately the endpoints that need no database row and no
external service: the health probe (used by Render), the schema endpoint
(the frontend's only source of truth for selectable fields), and the
input-validation paths. Anything that writes an Upload row is covered by
the pipeline unit tests instead, so the suite never mutates the local
dev database.

The app's startup hook creates tables and warms the embedding index over
the network, so the TestClient is deliberately NOT used as a context
manager — that keeps lifespan events from running.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from acf.fields import NON_EXTRACTABLE_TYPES, ACF_FIELDS
from main import app

pytestmark = pytest.mark.allow_httpx

client = TestClient(app)


# ──────────────────────────────── health ────────────────────────────────────


def test_health_returns_ok() -> None:
    """Render polls this; a non-200 takes the service out of rotation."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["timestamp"]


# ──────────────────────────────── schema ────────────────────────────────────


@pytest.mark.parametrize("page_type", ["university", "course", "specialization"])
def test_schema_lists_selectable_fields(page_type: str) -> None:
    response = client.get(f"/schema/{page_type}")
    assert response.status_code == 200
    body = response.json()
    assert body["page_type"] == page_type
    assert body["fields"]


@pytest.mark.parametrize("page_type", ["university", "course", "specialization"])
def test_schema_excludes_non_extractable_fields(page_type: str) -> None:
    """Images, files and relations are never valid correction targets in
    the Fix-Mappings UI — offering them lets an editor map a text section
    onto a field WordPress will reject."""
    returned = set(client.get(f"/schema/{page_type}").json()["fields"])
    excluded = {
        f["key"]
        for f in ACF_FIELDS[page_type]
        if f["type"] in NON_EXTRACTABLE_TYPES
    }
    assert not (returned & excluded), f"non-extractable fields leaked: {returned & excluded}"


@pytest.mark.parametrize("page_type", ["university", "course", "specialization"])
def test_schema_matches_the_source_of_truth(page_type: str) -> None:
    """The frontend must never need to hardcode this list."""
    expected = [
        f["key"]
        for f in ACF_FIELDS[page_type]
        if f["type"] not in NON_EXTRACTABLE_TYPES
    ]
    assert client.get(f"/schema/{page_type}").json()["fields"] == expected


@pytest.mark.parametrize("page_type", ["blog", "category", "nonsense"])
def test_schema_rejects_page_types_without_a_mapping_ui(page_type: str) -> None:
    response = client.get(f"/schema/{page_type}")
    assert response.status_code == 400


# ─────────────────────────── request validation ─────────────────────────────


def test_unknown_route_is_404() -> None:
    assert client.get("/definitely-not-a-route").status_code == 404


def test_upload_without_a_file_is_rejected() -> None:
    """422 from FastAPI's own validation — never a 500."""
    assert client.post("/upload").status_code == 422


def test_publish_with_a_non_numeric_id_is_rejected() -> None:
    response = client.post("/publish/not-an-int", json={"status": "draft"})
    assert response.status_code == 422


def test_cors_allows_the_browser_frontend() -> None:
    """The Vercel frontend calls this API cross-origin; without CORS
    every request fails in the browser but passes in curl."""
    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code in (200, 204)
    assert "access-control-allow-origin" in {
        k.lower() for k in response.headers
    }


def test_openapi_schema_builds() -> None:
    """A malformed response model breaks /docs for everyone; this catches
    it at test time instead."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.json()["paths"]


def test_every_documented_route_is_reachable() -> None:
    """Guards against a route being registered twice or shadowed."""
    paths = client.get("/openapi.json").json()["paths"]
    for expected in ("/health", "/upload", "/publish/{upload_id}", "/history"):
        assert expected in paths
