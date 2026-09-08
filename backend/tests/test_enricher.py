"""Tests for the deterministic enrichment helpers.

These fill fields the document implies but never states outright. They
are pure (no API calls), and they are where "the value looked fine in the
JSON but wrong on the page" bugs come from — a duration normalised into
the wrong unit, a fee picking up a phone number, or a syllabus that never
gets split into years and semesters.
"""

from __future__ import annotations

import pytest

from pipeline.enricher import (
    _derive_academic_years,
    _normalise_duration,
    _parse_indian_number,
    _strip_html,
    clean_filename,
    extract_duration_from_text,
    extract_emi_from_text,
    extract_fee_from_text,
)


# ─────────────────────────────── filenames ──────────────────────────────────


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("Copy of Mody University Page (1).docx", "Mody University"),
        ("Sharda Online MBA program.docx", "Sharda Online MBA"),
        # Underscores become spaces and "_final" is dropped. Note a version
        # marker still survives (see the xfail below).
        ("NMIMS_University_v2_final.docx", "NMIMS University v2"),
    ],
)
def test_clean_filename_strips_naming_noise(filename: str, expected: str) -> None:
    """The filename is the last-resort source for a page's name, so the
    noise ("Copy of", "(1)", "_final", the extension) has to come off."""
    assert clean_filename(filename) == expected


@pytest.mark.xfail(
    reason="clean_filename's docstring promises 'NMIMS University' but a "
    "trailing version marker (v2) survives, so it can reach a page title.",
    strict=True,
)
def test_clean_filename_should_strip_version_markers() -> None:
    assert clean_filename("NMIMS_University_v2_final.docx") == "NMIMS University"


def test_clean_filename_leaves_a_clean_name_alone() -> None:
    assert clean_filename("Sharda University") == "Sharda University"


# ────────────────────────────────── html ────────────────────────────────────


def test_strip_html_removes_tags() -> None:
    assert _strip_html("<p>Hello <strong>world</strong></p>").split() == [
        "Hello",
        "world",
    ]


# ───────────────────────────────── duration ─────────────────────────────────


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The programme runs for 2 years", "2 Years"),
        ("Duration: 24 months", "24 Months"),
        # Hyphenated form is common in marketing copy.
        ("A 2-year programme for professionals", "2 Years"),
    ],
)
def test_duration_is_found_in_prose(text: str, expected: str) -> None:
    assert extract_duration_from_text(text) == expected


def test_duration_absent_returns_none() -> None:
    assert extract_duration_from_text("No timing information here") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2 year", "2 Years"),
        ("1 years", "1 Year"),
        ("24 month", "24 Months"),
        ("2 Years", "2 Years"),
    ],
)
def test_duration_is_pluralised_and_title_cased(raw: str, expected: str) -> None:
    """The value is rendered verbatim on the page, so singular/plural and
    casing drift is visible to end users."""
    assert _normalise_duration(raw) == expected


# ────────────────────────────────── money ───────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,00,000", 100000),
        ("1,75,000", 175000),
        ("90000", 90000),
    ],
)
def test_indian_digit_grouping_is_parsed(raw: str, expected: int) -> None:
    assert _parse_indian_number(raw) == expected


def test_non_numeric_amount_is_none() -> None:
    assert _parse_indian_number("not a number") is None


def test_fee_is_extracted_from_prose() -> None:
    text = "The complete programme fee is INR 1,75,000 /- payable in instalments."
    assert "1,75,000" in (extract_fee_from_text(text) or "")


def test_fee_extraction_ignores_small_incidental_amounts() -> None:
    """An application fee or a phone number must not be mistaken for the
    programme fee — the extractor only accepts amounts above a floor."""
    text = "Pay the application fee of INR 1,000 to apply."
    assert extract_fee_from_text(text) is None


def test_emi_is_extracted_from_prose() -> None:
    text = "The monthly no-cost EMI is INR 7,292 /- for 24 months."
    assert "7,292" in (extract_emi_from_text(text) or "")


# ─────────────────────── syllabus → years and semesters ─────────────────────


def _syllabus(page_type: str, html: str) -> list[dict] | None:
    payload = {"syllabus_content": html}
    _derive_academic_years(payload, page_type, [])
    key = "course_academic_years" if page_type == "course" else "academic_years"
    return payload.get(key)


def test_syllabus_splits_into_years_and_semesters() -> None:
    """Regression: the syllabus used to publish as one flat blob, so
    WordPress could not display or sort it by year/semester."""
    html = (
        "<h3>Year I</h3>"
        "<h4>Semester 1</h4><p>Principles of Management</p>"
        "<h4>Semester 2</h4><p>Marketing Management</p>"
        "<h3>Year II</h3>"
        "<h4>Semester 3</h4><p>Strategic Management</p>"
    )
    years = _syllabus("specialization", html)
    assert [y["year_title"] for y in years] == ["Year I", "Year II"]
    assert [s["semester_title"] for s in years[0]["semesters"]] == [
        "Semester 1",
        "Semester 2",
    ]
    assert "Principles of Management" in years[0]["semesters"][0]["semester_subjects"]


def test_years_and_semesters_at_the_same_heading_level() -> None:
    """Real documents put both in <h4>; classifying by heading DEPTH
    instead of by the heading TEXT put every semester in its own year."""
    html = (
        "<h4>Year 1</h4>"
        "<h4>Semester I</h4><p>Subject A</p>"
        "<h4>Semester II</h4><p>Subject B</p>"
        "<h4>Year 2</h4>"
        "<h4>Semester III</h4><p>Subject C</p>"
    )
    years = _syllabus("specialization", html)
    assert len(years) == 2
    assert len(years[0]["semesters"]) == 2
    assert len(years[1]["semesters"]) == 1


def test_semesters_without_a_year_heading_still_get_grouped() -> None:
    html = "<h4>Semester 1</h4><p>Subject A</p><h4>Semester 2</h4><p>Subject B</p>"
    years = _syllabus("specialization", html)
    assert len(years) == 1
    assert len(years[0]["semesters"]) == 2


def test_course_pages_use_their_own_sub_field_names() -> None:
    """course and specialization have differently named sub-fields; using
    the wrong set 400s the whole repeater on publish."""
    html = "<h3>Year I</h3><h4>Semester 1</h4><p>Subject A</p>"
    years = _syllabus("course", html)
    assert "course_year_title" in years[0]
    assert "course_semester_title" in years[0]["course_semesters"][0]


def test_unrelated_headings_are_ignored() -> None:
    html = (
        "<h3>Overview</h3><p>Some intro</p>"
        "<h3>Year I</h3><h4>Semester 1</h4><p>Subject A</p>"
    )
    years = _syllabus("specialization", html)
    assert len(years) == 1
    assert years[0]["year_title"] == "Year I"


def test_syllabus_without_year_or_semester_headings_is_left_alone() -> None:
    """Non-destructive: a flat syllabus stays flat rather than being
    forced into a wrong structure."""
    assert _syllabus("specialization", "<p>A flat syllabus with no headings</p>") is None


def test_existing_repeater_value_is_never_overwritten() -> None:
    payload = {
        "syllabus_content": "<h3>Year I</h3><h4>Semester 1</h4><p>A</p>",
        "academic_years": [{"year_title": "Already extracted"}],
    }
    _derive_academic_years(payload, "specialization", [])
    assert payload["academic_years"] == [{"year_title": "Already extracted"}]


def test_university_pages_have_no_syllabus_structure() -> None:
    payload = {"syllabus_content": "<h3>Year I</h3><h4>Semester 1</h4><p>A</p>"}
    _derive_academic_years(payload, "university", [])
    assert "academic_years" not in payload
    assert "course_academic_years" not in payload


def test_enrichment_is_logged_for_the_ui() -> None:
    """The mapping UI shows provenance; an unlogged enrichment looks like
    it came from the document itself."""
    log: list[dict[str, str]] = []
    payload = {"syllabus_content": "<h3>Year I</h3><h4>Semester 1</h4><p>A</p>"}
    _derive_academic_years(payload, "specialization", log)
    assert any(e["field_key"] == "academic_years" for e in log)
    assert all(e["source"].startswith("derive:") for e in log)
