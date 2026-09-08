"""Tests for the payload validator / quality score.

The score drives the "is this document good enough to publish" signal in
the UI, so the statuses must mean what they say: RELATION fields are
skipped (not missing — nothing is wrong), genuinely short fields like a
NAAC grade are not "thin", and an empty repeater is missing.
"""

from __future__ import annotations

import pytest

from acf.fields import JSON_ARRAY, RELATION, TEXT
from pipeline.validator import get_field_status, validate_payload


# ─────────────────────────────── field status ───────────────────────────────


def test_relation_fields_are_skipped_not_missing() -> None:
    """They are resolved to post IDs at publish time, so flagging them as
    missing would permanently cap every course/specialization score."""
    assert get_field_status("linked_university", None, RELATION, 0) == "skipped"


@pytest.mark.parametrize("value", [None, "", [], {}])
def test_empty_values_are_missing(value: object) -> None:
    assert get_field_status("about_content", value, TEXT, 0) == "missing"


def test_short_prose_is_thin() -> None:
    assert get_field_status("about_content", "Too short.", "html", 2) == "thin"


def test_long_prose_is_mapped() -> None:
    assert get_field_status("about_content", "word " * 40, "html", 40) == "mapped"


@pytest.mark.parametrize(
    "field_key",
    ["naac_grade", "duration", "total_fee", "seo_title", "about_heading", "mode"],
)
def test_legitimately_short_fields_are_never_thin(field_key: str) -> None:
    """A NAAC grade is "A+" — two characters is a complete value, not a
    quality problem."""
    assert get_field_status(field_key, "A+", TEXT, 1) == "mapped"


def test_populated_repeater_is_mapped_regardless_of_word_count() -> None:
    assert get_field_status("faqs", [{"question": "Q"}], JSON_ARRAY, 1) == "mapped"


# ──────────────────────────────── whole payload ─────────────────────────────


def test_validation_report_shape() -> None:
    report = validate_payload({"university_name": "Sharda"}, "university")
    assert set(report["summary"]) >= {
        "total_required",
        "mapped",
        "thin",
        "missing",
        "quality_score",
    }
    assert report["field_report"]
    for entry in report["field_report"]:
        assert {"field_key", "status", "has_value"} <= set(entry)


def test_every_schema_field_appears_in_the_report() -> None:
    from acf.fields import get_valid_field_keys

    report = validate_payload({}, "course")
    reported = {e["field_key"] for e in report["field_report"]}
    # Relation fields are reported as "skipped" rather than omitted.
    assert reported == get_valid_field_keys("course")


def test_empty_payload_scores_zero() -> None:
    report = validate_payload({}, "university")
    assert report["summary"]["mapped"] == 0
    assert report["summary"]["quality_score"] == 0


def test_score_is_a_percentage() -> None:
    for page_type in ("university", "course", "specialization"):
        score = validate_payload({}, page_type)["summary"]["quality_score"]
        assert 0 <= score <= 100


def test_more_content_scores_higher() -> None:
    sparse = validate_payload({"university_name": "Sharda"}, "university")
    richer = validate_payload(
        {
            "university_name": "Sharda",
            "about_content": "word " * 50,
            "faqs": [{"question": "Q", "answer": "A"}],
            "seo_title": "Sharda University Online",
        },
        "university",
    )
    assert (
        richer["summary"]["quality_score"] > sparse["summary"]["quality_score"]
    )


def test_unknown_page_type_produces_an_empty_report() -> None:
    report = validate_payload({}, "not-a-page-type")
    assert report["field_report"] == []
    assert report["summary"]["total_required"] == 0


def test_meta_key_is_not_treated_as_a_field() -> None:
    """_meta rides along in the payload but is not an ACF field."""
    report = validate_payload({"_meta": {"page_type": "university"}}, "university")
    assert "_meta" not in {e["field_key"] for e in report["field_report"]}
