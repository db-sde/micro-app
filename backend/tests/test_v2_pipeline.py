"""Extraction v2 end to end behind EXTRACTION_PIPELINE: same persistence
and response shape as v1, flags that survive a reload and clear on edit,
and v1 still the default. Fake Anthropic client; throwaway SQLite.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from catalog import service as catalog_service
from db.database import Base, get_db
from db.models import FieldMapping, Upload
from main import app
from pipeline import service
from pipeline.v2 import claude
from tests.v2_helpers import course_answer, standard_client, upes_course_docx

pytest.importorskip("docling", reason="docling-slim[format-docx] is in requirements.txt")
pytestmark = pytest.mark.allow_httpx

FILENAME = "Copy of UPES Online MBA program.docx"
V1_KEYS = {"upload_id", "filename", "page_type", "payload", "validation", "field_mappings", "processing_time_ms"}


@pytest.fixture
def factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path}/v2.db", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    catalog_service.migrate(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


@pytest.fixture
def fake_claude(monkeypatch):
    client = standard_client()
    monkeypatch.setattr(claude, "get_client", lambda: client)
    monkeypatch.setenv("EXTRACTION_PIPELINE", "v2")
    return client


@pytest.fixture
def result(factory, fake_claude):
    with factory() as db:
        return service.run_extraction_pipeline(upes_course_docx(), FILENAME, "course", db)


def test_response_keeps_the_v1_shape(result) -> None:
    assert set(result) == V1_KEYS | {"pipeline", "extraction"}
    assert result["pipeline"] == "v2"
    assert result["page_type"] == "course"
    assert set(result["field_mappings"][0]) == {"field_key", "heading_in_doc", "confidence", "status", "source"}
    assert result["extraction"]["cost_usd"] > 0
    assert result["extraction"]["parser"] == "docling"


def test_payload_values(result) -> None:
    payload = result["payload"]
    assert payload["program_name"] == "UPES Online MBA"
    assert payload["admission_steps"].startswith("<p>Follow these steps to apply:</p><ol><li><strong>Step 1.")
    assert payload["admission_fee_note"].startswith("Additional information:")
    assert payload["emi_amount"] is None  # "N/A" from the model
    # exact table maths
    assert payload["course_amount_range"] == "INR 25,000 /- Semester – INR 40,000 /- Semester"
    assert payload["specialization"][1] == {"specialization_name": "Sales and Marketing",
                                            "specialization_details": "INR 40,000 /- Semester"}
    # heading fallback for a section with content but no heading of its own
    assert payload["fee_heading"] == "UPES Online MBA Fee Structure"
    # generated after the name was final
    assert payload["seo_title"].startswith("UPES Online MBA")
    # writer's Linked_ line becomes the relationship hint used at publish
    assert payload["_meta"]["relationship_hints"] == {"linked_university": "UPES Online"}
    assert payload["linked_university"] is None


def test_mappings_say_where_each_value_came_from(result) -> None:
    by_key = {}
    for m in result["field_mappings"]:
        by_key[m["field_key"]] = m  # the screens use the last record per field
    assert by_key["admission_steps"]["source"] == "LLM"
    assert by_key["admission_steps"]["heading_in_doc"] == "[admission_heading] UPES Online MBA Admission Process"
    assert by_key["admission_steps"]["confidence"] == 0.95
    assert by_key["admission_fee_note"]["confidence"] == 0.75
    assert by_key["course_amount_range"]["source"] == "DERIVED"
    assert by_key["seo_title"]["source"] == "AI_GENERATED"


def test_flags_are_in_the_validation_report(result) -> None:
    report = {r["field_key"]: r for r in result["validation"]["field_report"]}
    assert all("flags" in r for r in report.values())
    assert [f["code"] for f in report["emi_amount"]["flags"]] == ["derived"]
    assert report["fee_heading"]["flags"][0]["message"] == "Set by rule: heading_fallback"
    assert isinstance(result["validation"]["summary"]["flagged"], int)
    assert "course_syllabus_description" in report  # v2-only WordPress field is reported


def test_upload_and_mappings_are_saved(factory, result) -> None:
    with factory() as db:
        upload = db.get(Upload, result["upload_id"])
        stored = json.loads(upload.payload)
        assert stored["_meta"]["extraction"]["pipeline"] == "v2"
        assert stored["_meta"]["validation_flags"]
        rows = db.query(FieldMapping).filter(FieldMapping.upload_id == upload.id).all()
        assert len(rows) == len(result["field_mappings"])
        steps = next(r for r in rows if r.field_key == "admission_steps")
        assert steps.value.startswith("<p>Follow")  # /confirm carries this value over on a correction


def test_two_extraction_calls_and_one_generation_call(fake_claude, result) -> None:
    """Course pages extract text fields and lists in two requests (schema size), then write SEO/hero texts."""
    assert len(fake_claude.calls) == 3


@pytest.fixture
def api(factory):
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_flags_survive_a_reload_and_clear_when_the_field_is_edited(api, result) -> None:
    upload_id = result["upload_id"]
    got = api.get(f"/upload/{upload_id}").json()
    report = {r["field_key"]: r for r in got["validation"]["field_report"]}
    assert report["fee_heading"]["flags"]

    payload = got["payload"]
    payload["fee_heading"] = "UPES Online MBA Fees"
    patched = api.patch(f"/payload/{upload_id}", json={"payload": payload}).json()
    report = {r["field_key"]: r for r in patched["validation"]["field_report"]}
    assert report["fee_heading"]["flags"] == []          # edited -> its flag is gone
    assert report["emi_amount"]["flags"]                 # untouched -> kept


def test_problems_found_in_the_answer_are_flagged(factory, monkeypatch) -> None:
    bad = course_answer(accreditations_heading="AI FOR HUMAN RESOURCES : 1,96,000/-",
                        course_accreditations=[{"course_body_name": "UGC", "course_body_descriptor": "", "course_body_detail": ""}],
                        admission_fee_note="Step 2. Register online: Create an account on the UPES Online portal.")
    monkeypatch.setattr(claude, "get_client", lambda: standard_client(answer=bad))
    monkeypatch.setenv("EXTRACTION_PIPELINE", "v2")
    with factory() as db:
        out = service.run_extraction_pipeline(upes_course_docx(), FILENAME, "course", db)
    report = {r["field_key"]: r for r in out["validation"]["field_report"]}
    assert out["payload"]["accreditations_heading"] == "UPES Online MBA Accreditations"  # unusable -> fallback
    assert "note_is_a_step" in [f["code"] for f in report["admission_fee_note"]["flags"]]
    mappings = {m["field_key"]: m for m in out["field_mappings"]}
    assert mappings["admission_fee_note"]["confidence"] == 0.3


def test_v2_is_the_default(monkeypatch, factory) -> None:
    monkeypatch.delenv("EXTRACTION_PIPELINE", raising=False)

    class V2Ran(Exception):
        pass

    def v2_run(*_a, **_k):
        raise V2Ran

    monkeypatch.setattr(service, "parse_docx", lambda _b: pytest.fail("v1 must not run by default"))
    monkeypatch.setattr(service, "_run_v2_pipeline", v2_run)
    with factory() as db, pytest.raises(V2Ran):
        service.run_extraction_pipeline(b"", FILENAME, "course", db)


def test_v1_still_runs_when_chosen(monkeypatch, factory) -> None:
    monkeypatch.setenv("EXTRACTION_PIPELINE", "v1")

    class V1Ran(Exception):
        pass

    def v1_parse(_bytes):
        raise V1Ran

    monkeypatch.setattr(service, "parse_docx", v1_parse)
    monkeypatch.setattr(service, "_run_v2_pipeline", lambda *a, **k: pytest.fail("v2 must not run when v1 is chosen"))
    with factory() as db, pytest.raises(V1Ran):
        service.run_extraction_pipeline(b"", FILENAME, "course", db)


@pytest.mark.parametrize("value,expected", [("v2", "v2"), (" V2 ", "v2"), ("v1", "v1"), (" V1 ", "v1"), ("v3", "v2"), ("", "v2")])
def test_setting_values(monkeypatch, value, expected) -> None:
    monkeypatch.setenv("EXTRACTION_PIPELINE", value)
    assert service.extraction_pipeline() == expected


def test_page_type_is_detected_when_not_given(factory, fake_claude, monkeypatch) -> None:
    from pipeline.v2 import run
    monkeypatch.setattr(run, "_detect_page_type", lambda _bytes: "course")
    with factory() as db:
        out = service.run_extraction_pipeline(upes_course_docx(), FILENAME, None, db)
    assert out["page_type"] == "course"
