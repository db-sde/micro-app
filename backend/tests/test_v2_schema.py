"""Extraction v2: the JSON Schema for the single extraction call, the
committed WordPress schema snapshot, and the publish filter for v2-only
fields. No network: the live-schema fetch is exercised through fakes.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from acf.fields import ACF_FIELDS, get_v2_published_keys, get_v2_unpublished_keys
from pipeline import wordpress_client as wc
from pipeline.v2 import schema as s
from pipeline.v2 import wp_schema
from tests.conftest import FakeResponse

PAGE_TYPES = ("university", "course", "specialization")


def _walk(node: Any, path: str = "$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_schema_fits_structured_output_limits(page_type: str) -> None:
    """Structured outputs allow 16 union and 24 optional fields per request;
    this schema uses none: every object is closed and fully required."""
    schema = s.output_schema(page_type)
    for path, node in _walk(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False, path
            assert sorted(node["required"]) == sorted(node["properties"]), path
        assert "anyOf" not in node and not isinstance(node.get("type"), list), path
        for key in ("minimum", "maximum", "minLength", "maxLength"):
            assert key not in node, path


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_every_extracted_field_says_what_it_is_on_the_page(page_type: str) -> None:
    values = s.output_schema(page_type)["properties"]["values"]["properties"]
    assert values
    missing = [k for k, v in values.items() if not v.get("description")]
    assert missing == []


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_fields_never_in_a_document_are_not_asked_for(page_type: str) -> None:
    keys = {f["key"] for f in s.extracted_fields(page_type)}
    assert not keys & s.GENERATED_FIELDS[page_type]
    assert not keys & s.DERIVED_FIELDS[page_type]
    for f in ACF_FIELDS[page_type]:
        if f["type"] in ("image", "file", "relation"):
            assert f["key"] not in keys


@pytest.mark.parametrize("page_type", PAGE_TYPES)
def test_every_field_has_somewhere_to_go_on_the_live_site(page_type: str) -> None:
    """Catches drift between our registry and the live WordPress schema."""
    live = wp_schema.load_snapshot(page_type)
    renames = wc._PUBLISH_FIELD_RENAMES.get(page_type, {})
    transforms = {k: v[0] for k, v in wc._PUBLISH_HTML_LIST_TRANSFORMS.get(page_type, {}).items()}
    dropped_on_purpose = wc._PUBLISH_FIELD_DROP.get(page_type, set())
    keys = {f["key"] for f in s.extracted_fields(page_type)} | s.GENERATED_FIELDS[page_type] | s.DERIVED_FIELDS[page_type]
    nowhere = sorted(
        k for k in keys - get_v2_unpublished_keys(page_type) - dropped_on_purpose
        if (transforms.get(k) or renames.get(k, k)) not in live
    )
    assert nowhere == []


def test_v2_repeater_sub_fields_match_the_live_site() -> None:
    live = wp_schema.load_snapshot("specialization")["examination_process"]["sub_fields"]
    ours = s.output_schema("specialization")["properties"]["values"]["properties"]["examination_process"]
    assert sorted(ours["items"]["properties"]) == sorted(live)


def test_syllabus_is_asked_for_as_flat_semester_rows() -> None:
    """A list inside a list made the course/specialization grammar too large to compile."""
    years = s.output_schema("course")["properties"]["values"]["properties"]["course_academic_years"]
    assert sorted(years["items"]["properties"]) == ["course_semester_subjects", "course_semester_title", "course_year_title"]
    for page_type in ("course", "specialization"):
        values = s.output_schema(page_type)["properties"]["values"]["properties"]
        for key, prop in values.items():
            if prop["type"] == "array":
                assert all(v["type"] == "string" for v in prop["items"]["properties"].values()), key


def test_flat_semester_rows_are_nested_by_year() -> None:
    rows = [{"course_year_title": "Year I", "course_semester_title": "Semester I", "course_semester_subjects": "<ul><li>A</li></ul>"},
            {"course_year_title": "Year I", "course_semester_title": "Semester II", "course_semester_subjects": "<ul><li>B</li></ul>"},
            {"course_year_title": "Year II", "course_semester_title": "Semester III", "course_semester_subjects": "<ul><li>C</li></ul>"},
            {"course_year_title": "", "course_semester_title": "Semester IV", "course_semester_subjects": "<ul><li>D</li></ul>"}]
    years = s.to_payload("course", {"course_academic_years": rows})["course_academic_years"]
    assert [y["course_year_title"] for y in years] == ["Year I", "Year II"]
    assert [[sem["course_semester_title"] for sem in y["course_semesters"]] for y in years] == [
        ["Semester I", "Semester II"], ["Semester III", "Semester IV"]]


def test_field_groups_cover_every_field_once() -> None:
    for page_type in ("university", "course", "specialization"):
        groups = s.field_groups(page_type)
        flat = [k for g in groups for k in g]
        assert sorted(flat) == sorted(f["key"] for f in s.extracted_fields(page_type))
        assert len(flat) == len(set(flat))
        partial = s.output_schema(page_type, groups[1])["properties"]["values"]["properties"]
        assert set(partial) == set(groups[1])


def test_provenance_names_fields_as_plain_text() -> None:
    field = s.output_schema("course")["properties"]["provenance"]["items"]["properties"]["field"]
    assert field["type"] == "string" and "enum" not in field


def test_empty_values_become_null_and_blank_rows_are_dropped() -> None:
    values = {
        "program_name": "  Jamia Online MBA ",
        "emi_amount": "",
        "faqs": [{"question": "", "answer": ""}, {"question": "Is it valid?", "answer": "Yes."}],
        "job_profiles": [],
        "course_academic_years": [{"course_year_title": "Year I", "course_semesters": [
            {"course_semester_title": "Semester I", "course_semester_subjects": "<ul><li>A</li></ul>"},
            {"course_semester_title": "", "course_semester_subjects": ""}]}],
    }
    payload = s.to_payload("course", values)
    assert payload["program_name"] == "Jamia Online MBA"
    assert payload["emi_amount"] is None
    assert payload["faqs"] == [{"question": "Is it valid?", "answer": "Yes."}]
    assert payload["job_profiles"] is None
    assert len(payload["course_academic_years"][0]["course_semesters"]) == 1
    assert payload["about_content"] is None  # absent from the model output


# ── live schema snapshot ──────────────────────────────────────────────

_OPTIONS_BODY = {"schema": {"properties": {"acf": {"properties": {
    "total_fee": {"type": ["string", "null"], "required": False},
    "other_specs": {"type": ["array", "null"], "items": {"type": "object", "properties": {
        "other_spec_name": {"type": ["string", "null"]}, "other_spec_fee": {"type": ["string", "null"]}}}},
}}}}}


class _FakeOptionsClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def options(self, url: str) -> FakeResponse:
        self.urls.append(url)
        return self.response


def test_options_response_is_trimmed_to_types_and_sub_fields() -> None:
    client = _FakeOptionsClient(FakeResponse(_OPTIONS_BODY))
    acf = wp_schema.fetch_live("specialization", site="https://wp.test/", client=client)
    assert client.urls == ["https://wp.test/wp-json/wp/v2/specialization"]
    assert acf["other_specs"]["sub_fields"] == {"other_spec_fee": {"type": ["string", "null"]},
                                               "other_spec_name": {"type": ["string", "null"]}}
    assert "required" not in acf["total_fee"]


def test_live_schema_falls_back_to_the_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(wp_schema, "CACHE_DIR", tmp_path)

    def _down(*_a, **_k):
        raise RuntimeError("406 from the firewall")

    monkeypatch.setattr(wp_schema, "fetch_live", _down)
    assert wp_schema.load_schema("course", live=True) == wp_schema.load_snapshot("course")


def test_live_schema_is_cached_on_disk(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(wp_schema, "CACHE_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(wp_schema, "fetch_live", lambda pt: calls.append(pt) or {"total_fee": {"type": "string"}})
    assert wp_schema.load_schema("course", live=True) == {"total_fee": {"type": "string"}}
    assert wp_schema.load_schema("course", live=True) == {"total_fee": {"type": "string"}}
    assert calls == ["course"]
    assert json.loads((tmp_path / "course.json").read_text())["total_fee"]["type"] == "string"


def test_snapshot_is_used_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("V2_LIVE_SCHEMA", raising=False)
    monkeypatch.setattr(wp_schema, "fetch_live", lambda *_a, **_k: pytest.fail("no network by default"))
    assert "total_fee" in wp_schema.load_schema("course")


# ── publish filter ────────────────────────────────────────────────────

def _publish_capture(monkeypatch, fake_httpx_client, payload: dict, page_type: str) -> dict:
    monkeypatch.setattr(wc, "_derive_taxonomies", lambda *a, **k: ({}, []))
    monkeypatch.setattr(wc, "_derive_relationships", lambda *a, **k: ({}, []))
    holder = fake_httpx_client(FakeResponse({"id": 7, "link": "https://wp.test/x", "status": "draft"}))
    wc.publish_payload(payload, page_type)
    posts = [c for client in holder.created for c in client.calls if c["method"] == "POST"]
    return posts[-1]["json"]["acf"]


def test_v2_wordpress_fields_are_published_and_intros_are_not(monkeypatch, fake_httpx_client, wp_configured) -> None:
    payload = {
        "spec_name": "DevOps",
        "examination_process": [{"exam_process_title": "Exam Mode", "exam_process_description": "Online, proctored"}],
        "specialization_lowest_emi_strats_from": "10,156",
        "syllabus_description": "The syllabus spans four semesters.",
        "fee_intro": "Fees are payable per semester.",
    }
    acf = _publish_capture(monkeypatch, fake_httpx_client, payload, "specialization")
    assert acf["examination_process"] == payload["examination_process"]
    assert acf["specialization_lowest_emi_strats_from"] == "10,156"
    assert acf["syllabus_description"] == "The syllabus spans four semesters."
    assert "fee_intro" not in acf


def test_v1_payload_publishes_exactly_as_before(monkeypatch, fake_httpx_client, wp_configured) -> None:
    """v1 never produces v2-only keys, so the wider filter changes nothing for it."""
    payload = {"spec_name": "DevOps", "total_fee": "INR 1,30,000 /-", "not_a_field": "x"}
    acf = _publish_capture(monkeypatch, fake_httpx_client, payload, "specialization")
    assert acf["total_fee"] == "INR 1,30,000 /-"
    assert "not_a_field" not in acf
    assert not set(acf) & (get_v2_published_keys("specialization") - {"syllabus_description", "syllabus_section_heading"})
