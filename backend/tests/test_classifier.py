"""Tests for the three-tier heading classifier.

Writers prefix a heading with [field_name] to bind it to an ACF field.
Tier 1 is a direct hit (no embedding), Tier 2 is a typo'd tag (strip it,
embed the clean text), Tier 3 is an untagged heading. The subtle part is
heading/content pairing: a lone [x_heading] tag must also pull in the
field holding that section's BODY, and the body field's name differs by
page type — accreditations on university, course_accreditations on
course. Hardcoding one name silently dropped the body on the other.
"""

from __future__ import annotations

import pytest

from acf.fields import get_valid_field_keys
from pipeline.classifier import classify_heading

UNIVERSITY = get_valid_field_keys("university")
COURSE = get_valid_field_keys("course")
SPECIALIZATION = get_valid_field_keys("specialization")


# ──────────────────────────────── tiers ─────────────────────────────────────


def test_tier1_valid_tag_routes_directly() -> None:
    result = classify_heading("[about_content] About the University", UNIVERSITY)
    assert result["route"] == "direct"
    assert result["tier"] == 1
    assert "about_content" in result["field_keys"]
    assert result["display"] == "About the University"
    assert result["embed_heading"] is None


def test_tier2_typo_tag_falls_back_to_embedding_on_clean_text() -> None:
    """The bad tag is stripped so it doesn't poison the embedding."""
    result = classify_heading("[abuot_contnt] About the University", UNIVERSITY)
    assert result["route"] == "embedding"
    assert result["tier"] == 2
    assert result["display"] == "About the University"
    assert result["embed_heading"] == "About the University"
    assert result["tag_found"] == "abuot_contnt"


def test_tier3_untagged_heading_embeds_the_whole_heading() -> None:
    result = classify_heading("About the University", UNIVERSITY)
    assert result["route"] == "embedding"
    assert result["tier"] == 3
    assert result["embed_heading"] == "About the University"
    assert result["tag_found"] is None


def test_tag_only_heading_uses_the_tag_as_display_text() -> None:
    result = classify_heading("[faqs]", UNIVERSITY)
    assert result["route"] == "direct"
    assert result["display"] == "faqs"


@pytest.mark.parametrize(
    "heading",
    ["[About_Content] Title", "[about content] Title", "[about-content] Title"],
)
def test_tag_normalisation_accepts_case_spaces_and_hyphens(heading: str) -> None:
    result = classify_heading(heading, UNIVERSITY)
    assert result["route"] == "direct"
    assert "about_content" in result["field_keys"]


# ───────────────────────── heading → content pairing ────────────────────────


def test_lone_heading_tag_also_pulls_in_its_content_field() -> None:
    """Without the pairing the section body is dropped and only the
    heading title is stored."""
    result = classify_heading("[faqs_heading] Frequently Asked Questions", UNIVERSITY)
    assert result["route"] == "direct"
    assert set(result["field_keys"]) == {"faqs_heading", "faqs"}


def test_accreditations_heading_pairs_with_the_university_body_field() -> None:
    result = classify_heading("[accreditations_heading] Accreditations", UNIVERSITY)
    assert set(result["field_keys"]) == {"accreditations_heading", "accreditations"}


def test_accreditations_heading_pairs_with_the_course_body_field() -> None:
    """Regression: the pairing table pointed only at "accreditations",
    which does not exist on course pages, so a course document's
    accreditation rows never populated."""
    result = classify_heading("[accreditations_heading] Accreditations", COURSE)
    assert set(result["field_keys"]) == {
        "accreditations_heading",
        "course_accreditations",
    }


def test_pairing_never_invents_a_field_absent_from_the_page_type() -> None:
    """Only fields valid for THIS page type may be emitted, or publish
    fails with "Invalid parameter(s): acf"."""
    for page_type_fields in (UNIVERSITY, COURSE, SPECIALIZATION):
        result = classify_heading("[accreditations_heading] X", page_type_fields)
        for key in result.get("field_keys", []):
            assert key in page_type_fields


# ───────────────────────────── multi-tag headings ───────────────────────────


def test_comma_tag_prefers_content_fields_over_heading_fields() -> None:
    """Heading fields are auto-filled elsewhere; the content field is the
    one that actually needs the section body routed to it."""
    result = classify_heading(
        "[about_heading,about_content] About the University", UNIVERSITY
    )
    assert result["route"] == "direct"
    assert "about_content" in result["field_keys"]
    assert "about_heading" not in result["field_keys"]


def test_comma_tag_of_only_heading_fields_still_maps() -> None:
    result = classify_heading("[about_heading,faqs_heading] Title", UNIVERSITY)
    assert result["route"] == "direct"
    assert set(result["field_keys"]) == {"about_heading", "faqs_heading"}


def test_comma_tag_ignores_members_invalid_for_the_page_type() -> None:
    result = classify_heading(
        "[about_content,not_a_real_field] About", UNIVERSITY
    )
    assert result["field_keys"] == ["about_content"]


def test_comma_tag_with_no_valid_member_falls_back_to_embedding() -> None:
    result = classify_heading("[nope,also_nope] Some Heading", UNIVERSITY)
    assert result["route"] == "embedding"
    assert result["tier"] == 2
    assert result["embed_heading"] == "Some Heading"


def test_page_type_scoping_rejects_a_tag_from_another_template() -> None:
    """fee_plans is a course/specialization field. A university document
    reusing that tag must not have it accepted."""
    assert "fee_plans" not in UNIVERSITY
    result = classify_heading("[fee_plans] Fee Structure", UNIVERSITY)
    assert result["route"] == "embedding"


# ──────────────────────────────── robustness ────────────────────────────────


def test_leading_whitespace_is_tolerated() -> None:
    result = classify_heading("   [faqs] Questions", UNIVERSITY)
    assert result["route"] == "direct"


def test_empty_heading_is_tier3_and_does_not_raise() -> None:
    result = classify_heading("", UNIVERSITY)
    assert result["route"] == "embedding"
    assert result["tier"] == 3


def test_unclosed_bracket_is_treated_as_plain_text() -> None:
    result = classify_heading("[about_content About the University", UNIVERSITY)
    assert result["route"] == "embedding"
    assert result["tier"] == 3
