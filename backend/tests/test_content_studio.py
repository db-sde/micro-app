"""Pages go to Content Studio (senior review) instead of WordPress.

The parser hands over its fields (after its content clean-up), its flags and
the original Word document; Content Studio publishes. Publishing
university / course / specialization pages to WordPress from the parser is
off unless ALLOW_WORDPRESS_PUBLISH=1.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from catalog import service as catalog_service
from db.database import Base, get_db
from db.models import Upload, UploadDocument
from main import app
from pipeline import content_studio
from pipeline.service import _persist_and_respond

SECRET = "test-content-studio-secret-0123456789abcdef"
URL = "https://studio.test"

PAYLOAD = {
    "program_name": "Jamia Islamia Online MBA",
    "university_name": "Jamia Islamia Online",
    "duration": "2 Years",
    "validity": "Validity is not mentioned",
    "top_hiring_partners_course": "<ul><li>KPMG</li><li>Adobe</li><li>Microsoft</li></ul>",
    "placement_content": "<p>Placement support is offered.</p><p>Major recruiters include:</p>"
                         "<ul><li>KPMG</li><li>Adobe</li><li>Microsoft, etc</li></ul>",
    "admission_steps": "<p>Apply:</p><p>Step 1. Register.</p><p>Step 2. Pay.</p>",
    "hero_image": "https://res.cloudinary.com/x/hero.jpg",
    "_meta": {
        "document_title": "Copy of Jamia Islamia Online MBA program.docx",
        "relationship_hints": {"linked_university": "Jamia Millia Islamia Online"},
        "validation_flags": [
            {"field_key": "placement_content", "code": "x", "severity": "warning", "message": "Names repeated."},
            {"field_key": "program_name", "code": "derived", "severity": "info", "message": "Set by rule"},
        ],
    },
}


class Studio:
    """Stand-in Content Studio import route: checks the signature like the real one."""

    def __init__(self, status=201):
        self.status, self.calls = status, []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = request.content
        ts = request.headers["x-parser-timestamp"]
        expected = hmac.new(SECRET.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
        assert request.url.path == "/api/import/parser-draft"
        assert hmac.compare_digest(expected, request.headers["x-parser-signature"])
        assert abs(time.time() - int(ts)) < 60
        self.calls.append(json.loads(body))
        if self.status >= 400:
            return httpx.Response(self.status, json={"error": "nope"})
        return httpx.Response(201, json={"draftId": "draft_1", "status": "senior_review", "existed": False, "unmapped": []})


@pytest.fixture
def studio(monkeypatch):
    monkeypatch.setenv("CONTENT_STUDIO_URL", URL)
    monkeypatch.setenv("CONTENT_STUDIO_IMPORT_SECRET", SECRET)
    stub = Studio()
    transport = httpx.MockTransport(stub.handle)

    class Shim:
        def Client(self, *a, **k):  # noqa: N802
            return httpx.Client(*a, transport=transport, **k)

        def __getattr__(self, name):
            return getattr(httpx, name)

    monkeypatch.setattr(content_studio, "httpx", Shim())
    return stub


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/cs.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    catalog_service.migrate(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def api(factory):
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_upload(factory, page_type="course", document=b"PK docx bytes"):
    with factory() as db:
        u = Upload(filename="Copy of Jamia Islamia Online MBA program.docx", page_type=page_type,
                   status="processed", payload=json.dumps(PAYLOAD))
        db.add(u)
        db.flush()
        if document:
            db.add(UploadDocument(upload_id=u.id, filename=u.filename, content=document))
        db.commit()
        return u.id


def test_the_content_clean_up_is_applied_before_handing_over():
    out = content_studio.prepare_payload(json.loads(json.dumps(PAYLOAD)), "course")
    assert out["program_name"] == "Jamia Islamia Online MBA program"        # the document's top line
    assert "KPMG" not in out["placement_content"]                          # names shown once, as chips
    assert out["admission_steps"].count("<li>") == 2                        # one numbered list
    assert out["validity"] is None                                          # "not mentioned" -> empty
    assert "_meta" not in out


@pytest.mark.usefixtures("allow_mock_transport")
def test_send_is_signed_and_carries_the_document_flags_and_links(studio):
    result = content_studio.send(7, "Doc.docx", "course", json.loads(json.dumps(PAYLOAD)), b"PK docx")
    assert result["draftId"] == "draft_1"
    sent = studio.calls[0]
    assert sent["pageType"] == "course" and sent["uploadId"] == "7"
    assert base64.b64decode(sent["document"]) == b"PK docx"
    assert sent["relationshipHints"] == {"linked_university": "Jamia Millia Islamia Online"}
    messages = [f["message"] for f in sent["flags"]]
    assert "Names repeated." in messages and "Set by rule" not in messages      # warnings only
    assert any("hero.jpg" in m for m in messages)                               # uploaded image passed on


@pytest.fixture
def app_and_studio_only(monkeypatch):
    """Let through only the in-process app (TestClient) and the stand-in Content Studio."""
    from tests.conftest import _ORIGINAL_SEND

    def send(client, *args, **kwargs):
        transport = client._transport
        if isinstance(transport, httpx.MockTransport) or type(transport).__module__ == "starlette.testclient":
            return _ORIGINAL_SEND(client, *args, **kwargs)
        raise AssertionError("real network call attempted")
    monkeypatch.setattr(httpx.Client, "send", send)


@pytest.mark.usefixtures("app_and_studio_only")
def test_send_endpoint_marks_the_upload_as_in_content_studio(api, factory, studio):
    uid = add_upload(factory)
    res = api.post(f"/send-to-content-studio/{uid}")
    assert res.status_code == 200, res.text
    assert res.json()["draft_id"] == "draft_1" and res.json()["with_document"] is True
    with factory() as db:
        u = db.get(Upload, uid)
        assert u.status == "sent_to_studio"
        assert json.loads(u.payload)["_meta"]["content_studio"]["draft_id"] == "draft_1"


@pytest.mark.allow_httpx
def test_not_connected_gives_a_clear_message(api, factory):
    uid = add_upload(factory)
    res = api.post(f"/send-to-content-studio/{uid}")
    assert res.status_code == 502
    assert "CONTENT_STUDIO_URL" in res.json()["detail"]


@pytest.mark.allow_httpx
@pytest.mark.parametrize("page_type", ["university", "course", "specialization"])
def test_parser_no_longer_publishes_these_pages_to_wordpress(api, factory, page_type):
    uid = add_upload(factory, page_type=page_type)
    res = api.post(f"/publish/{uid}", json={"status": "publish"})
    assert res.status_code == 410
    assert "Content Studio" in res.json()["detail"]


def test_the_word_document_is_kept_with_the_upload(factory):
    with factory() as db:
        out = _persist_and_respond({"_meta": {}, "program_name": "X"}, [], {"summary": {"quality_score": 90}, "field_report": []},
                                   "course", "X.docx", db, time.time(), b"PK the document")
        doc = db.get(UploadDocument, out["upload_id"])
        assert doc.content == b"PK the document" and doc.filename == "X.docx"


@pytest.mark.allow_httpx
def test_deleting_an_upload_deletes_its_document(api, factory):
    uid = add_upload(factory)
    assert api.delete(f"/history/{uid}").status_code in (200, 204)
    with factory() as db:
        assert db.get(UploadDocument, uid) is None
