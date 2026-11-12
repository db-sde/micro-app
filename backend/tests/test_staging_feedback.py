"""Fixes from the team's review of pages published to staging (12 Nov)."""

from __future__ import annotations

import pytest

from pipeline import wordpress_client as wc
from pipeline.validator import validate_payload

PARTNERS = "<ul><li>Pepsi</li><li>Amazon</li><li>HCL</li></ul>"


def test_galgotias_note_after_the_steps_leaves_the_steps_box():
    html = ("<p>The admission process:</p><ol><li><strong>Step 1.</strong> Register.</li><li><strong>Step 2.</strong> Pay.</li></ol>"
            "<p>Note: The application fee is INR 1,200 /- (non-refundable).</p>")
    out = wc._polish_for_wordpress({"admission_steps": html}, "specialization")
    assert out["admission_steps"].endswith("</ol>") and "INR 1,200" not in out["admission_steps"]
    assert not out.get("admission_fee_note")  # typed by the team


def test_partner_names_are_shown_once_as_chips_not_again_in_the_placement_text():
    """Sharda Finance / Symbiosis BBA showed the names twice."""
    acf = {"hiring_partners_specialization": PARTNERS,
           "placement_content": "<p>Placement support includes resume building.</p>"
                                "<p>Some of the active recruiters of Sharda online MBA graduates include:</p>"
                                "<ul><li>Pepsi</li><li>Amazon</li><li>HCL</li></ul>"}
    wc._dedupe_partner_list(acf, "specialization")
    assert acf["placement_content"] == "<p>Placement support includes resume building.</p>"


def test_other_sentences_in_the_lead_in_paragraph_are_kept():
    acf = {"hiring_partners_specialization": PARTNERS,
           "placement_content": "<p>The university also offers master classes. Some of the active recruiters include:</p>"
                                "<ul><li>Pepsi</li><li>Amazon</li><li>HCL</li></ul>"}
    wc._dedupe_partner_list(acf, "specialization")
    assert acf["placement_content"] == "<p>The university also offers master classes.</p>"


def test_a_list_that_is_not_the_partners_is_kept():
    acf = {"top_hiring_partners_course": PARTNERS,
           "placement_content": "<p>Services include:</p><ul><li>Resume building</li><li>Mock interviews</li></ul>"}
    before = acf["placement_content"]
    wc._dedupe_partner_list(acf, "course")
    assert acf["placement_content"] == before


def test_syllabus_without_years_fills_the_accordion_by_subject_group():
    """EIMT DBA: 'Core Courses' / 'Research' groups, no year/semester table."""
    html = "<h3>Core Courses</h3><ul><li>Strategic Marketing</li><li>Corporate Governance</li></ul><h3>Research</h3><ul><li>Thesis</li></ul>"
    rows = wc._syllabus_years_from_content({"syllabus_content": html}, "course")["course_academic_years"]
    assert [r["course_year_title"] for r in rows] == ["Core Courses", "Research"]
    assert rows[0]["course_semesters"][0]["course_semester_subjects"] == "<ul><li>Strategic Marketing</li><li>Corporate Governance</li></ul>"
    # never replaces a real year/semester syllabus
    assert wc._syllabus_years_from_content({"syllabus_content": html, "course_academic_years": [{"course_year_title": "Year I"}]}, "course") == {}


def test_syllabus_keeps_its_own_first_heading():
    html = "<h3>Core Courses</h3><ul><li>Strategic Marketing</li></ul>"
    assert wc._polish_for_wordpress({"syllabus_content": html}, "course")["syllabus_content"] == html


@pytest.mark.usefixtures("allow_mock_transport")
@pytest.mark.parametrize("site_type,expected", [(["string", "null"], "3 Years"), (["number", "null"], 3)])
def test_program_duration_keeps_its_unit_when_wordpress_has_it_as_text(monkeypatch, site_type, expected):
    from evals.projection import FakeWordPress, _fake_site
    site = {"program_name": ["string", "null"], "duration": ["string", "null"], "program_duration": site_type}
    monkeypatch.setattr(wc, "_get_live_acf_field_types", lambda post_type: site)
    fake = FakeWordPress()
    with _fake_site(fake, raw=False):
        wc.publish_payload({"program_name": "EIMT Online DBA", "duration": "3 Years"}, "course", status="draft")
    assert fake.sent_acf()["program_duration"] == expected


def test_optional_fields_are_not_counted_as_missing():
    """'12 missing fields' on a specialization upload: partner banks, intros, certificate heading..."""
    payload = {"spec_name": "Finance", "_meta": {"extra_fields": ["partner_banks_specialization", "eligibility_intro"]}}
    report = {r["field_key"]: r["status"] for r in validate_payload(payload, "specialization", flags=[])["field_report"]}
    assert report["partner_banks_specialization"] == "skipped"
    assert report["eligibility_intro"] == "skipped"
    assert report["certificate_heading"] == "skipped"
    assert report["total_fee"] == "missing"  # core fields still count


def test_specialization_titled_document_is_not_published_as_a_course(monkeypatch):
    """'Uttaranchal University Online MBA in Business Analytics' was auto-detected as a course."""
    from pipeline.v2 import run
    monkeypatch.setattr(run, "_detect_page_type", lambda b: "course")
    seen = {}

    def fake_extract(md, page_type, title, model=None, client=None):
        seen["page_type"] = page_type
        raise RuntimeError("stop")

    monkeypatch.setattr(run, "extract", fake_extract)
    monkeypatch.setattr(run, "to_markdown", lambda b, f: type("D", (), {"markdown": "", "tables": [], "parser": "docling", "error": None})())
    with pytest.raises(RuntimeError, match="stop"):
        run.run_v2(b"", "Copy of Uttaranchal University Online MBA in Business Analytics.docx", None)
    assert seen["page_type"] == "specialization"
    seen.clear()
    with pytest.raises(RuntimeError):
        run.run_v2(b"", "Copy of Uttaranchal University Online MBA in Business Analytics.docx", "course")  # chosen by hand: kept
    assert seen["page_type"] == "course"
