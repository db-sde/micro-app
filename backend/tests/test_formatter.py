"""Tests for build_json_output — the final payload assembly step.

Its one subtlety is the RELATION fields (linked_university,
linked_course, category_page). The ACF field itself must always be null
here, because WordPress wants a post ID and a document only ever contains
a NAME. But that name is exactly what publish-time relationship
resolution needs, so it is preserved under _meta.relationship_hints
instead of being discarded — which is what used to happen, leaving
linked_university permanently unresolvable.
"""

from __future__ import annotations

from acf.fields import SKIP_EXTRACTION_FIELDS
from pipeline.formatter import build_json_output


def _fields(**kwargs: object) -> list[dict[str, object]]:
    return [{"field_key": k, "value": v} for k, v in kwargs.items()]


def test_meta_block_is_always_present() -> None:
    payload = build_json_output([], "Doc.docx", "university")
    assert payload["_meta"]["document_title"] == "Doc.docx"
    assert payload["_meta"]["page_type"] == "university"
    assert payload["_meta"]["generated_by"] == "DegreeBaba Content Publisher"


def test_ordinary_values_pass_through_untouched() -> None:
    payload = build_json_output(
        _fields(university_name="Sharda University Online", num_programs="15"),
        "Doc.docx",
        "university",
    )
    assert payload["university_name"] == "Sharda University Online"
    assert payload["num_programs"] == "15"


def test_relation_fields_are_always_null_in_the_payload() -> None:
    """WordPress expects post IDs here; a name string would 400 the
    publish, so the field itself is never populated from the document."""
    payload = build_json_output(
        _fields(linked_university="UPES Online", linked_course="UPES Online MBA"),
        "Doc.docx",
        "specialization",
    )
    assert payload["linked_university"] is None
    assert payload["linked_course"] is None


def test_relationship_names_are_preserved_as_hints() -> None:
    """Regression: these names were discarded outright, so publish-time
    resolution had nothing authoritative to match on and fell back to a
    filename guess."""
    payload = build_json_output(
        _fields(linked_university="UPES Online", linked_course="UPES Online MBA"),
        "Copy of UPES Online MBA in Marketing Management.docx",
        "specialization",
    )
    assert payload["_meta"]["relationship_hints"] == {
        "linked_university": "UPES Online",
        "linked_course": "UPES Online MBA",
    }


def test_no_hints_key_when_the_document_names_nothing() -> None:
    """Absence must be distinguishable from an empty match, so the key is
    omitted rather than set to an empty dict."""
    payload = build_json_output(
        _fields(university_name="Sharda University Online"), "Doc.docx", "course"
    )
    assert "relationship_hints" not in payload["_meta"]


def test_empty_relation_values_do_not_create_hints() -> None:
    payload = build_json_output(
        _fields(linked_university="", linked_course=None),
        "Doc.docx",
        "specialization",
    )
    assert "relationship_hints" not in payload["_meta"]
    assert payload["linked_university"] is None


def test_every_skip_extraction_field_is_nulled_and_hinted() -> None:
    """Covers all RELATION fields, so a newly added one can't quietly
    skip the hint path."""
    values = {key: f"Name for {key}" for key in SKIP_EXTRACTION_FIELDS}
    payload = build_json_output(_fields(**values), "Doc.docx", "course")
    for key in SKIP_EXTRACTION_FIELDS:
        assert payload[key] is None, f"{key} should be null in the payload"
    assert payload["_meta"]["relationship_hints"] == values


def test_hints_never_leak_into_the_publishable_field_set() -> None:
    """_meta is stripped before the acf object is sent; hints must live
    only there, never as a top-level key that could reach WordPress."""
    payload = build_json_output(
        _fields(linked_university="UPES Online"), "Doc.docx", "specialization"
    )
    assert "relationship_hints" not in payload
