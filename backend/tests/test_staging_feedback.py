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



def test_partner_extraction_keeps_the_other_bullet_lists():
    """UPES/Manav Rachna: the services list became one <p> per line on WordPress."""
    html = ("<p>Services include:</p><ul><li>Career Orientation</li><li>Interview preparation</li></ul>"
            "<p>Some of the major hiring partners are:</p><p>FedEx</p><p>Amazon</p><p>KPMG</p>")
    names, out = wc._placement_partners(html)
    assert names == ["FedEx", "Amazon", "KPMG"]
    assert out.startswith("<p>Services include:</p><ul><li>Career Orientation</li><li>Interview preparation</li></ul>")
    assert out.endswith("<ul><li>FedEx</li><li>Amazon</li><li>KPMG</li></ul>")
    listed = "<p>Top recruiters are:</p><ul><li>FedEx</li><li>Amazon</li></ul>"
    assert wc._placement_partners(listed) == (["FedEx", "Amazon"], listed)


@pytest.mark.parametrize("lead,kept", [
    ("The institution has 800+ recruiters who annually hire skilled graduates, some of whom are:",
     "The institution has 800+ recruiters who annually hire skilled graduates."),
    ("The Manav Rachna CDOE has 200+ hiring partners, some of which are as follows:", "The Manav Rachna CDOE has 200+ hiring partners."),
    ("The university has 500+ hiring partners, among which the most prominent ones are mentioned below:", "The university has 500+ hiring partners."),
])
def test_placement_stats_survive_when_the_partner_list_is_removed(lead, kept):
    acf = {"hiring_partners_specialization": PARTNERS,
           "placement_content": f"<p>{lead}</p><ul><li>Pepsi</li><li>Amazon</li><li>HCL</li></ul>"}
    wc._dedupe_partner_list(acf, "specialization")
    assert acf["placement_content"] == f"<p>{kept}</p>"


def test_eligibility_note_that_repeats_a_criterion_is_dropped():
    crit = "The applicant must have completed 12th grade from a recognized board."
    out = wc._polish_for_wordpress({"eligibility_summary": crit,
                                    "eligibility_content": [{"eligibility_title": "Qualification", "eligibility_description": crit}]}, "course")
    assert out["eligibility_summary"] is None
    other = wc._polish_for_wordpress({"eligibility_summary": "Working professionals get preference.",
                                      "eligibility_content": [{"eligibility_title": "Qualification", "eligibility_description": crit}]}, "course")
    assert other["eligibility_summary"] == "Working professionals get preference."


def test_validity_copied_from_the_duration_is_dropped():
    assert wc._polish_for_wordpress({"duration": "3 Years", "validity": "3 years"}, "course")["validity"] is None
    assert wc._polish_for_wordpress({"duration": "2 Years", "validity": "4 Years"}, "course")["validity"] == "4 Years"


@pytest.mark.parametrize("key,value", [("program_validity", "Validity is also not Mentioned"),
                                       ("emi_amount", "EMI is not offered by The University"),
                                       ("validity", "Not specified"), ("num_specializations", "0 (Not offered)"),
                                       ("num_specializations", "0")])
def test_values_the_document_says_are_not_given_stay_empty(key, value):
    """TNOU BCom / LPU BA pages showed 'Validity is also not Mentioned' and '0 (Not offered)'."""
    assert wc._polish_for_wordpress({key: value}, "course")[key] is None


def test_free_text_mentioning_not_offered_is_kept():
    text = "<p>Since no specializations are offered, students gain a broad understanding.</p>"
    assert wc._polish_for_wordpress({"about_content": text}, "course")["about_content"] == text
    assert wc._polish_for_wordpress({"num_specializations": "8+"}, "course")["num_specializations"] == "8+"


def test_other_specs_come_from_the_programs_fee_table():
    """NIU MBA in Business Analytics: 'offered in 7 specializations', but 3 extra names without a fee were listed."""
    from pipeline.v2 import derive
    table = [["Specialization", "Fee per semester"], ["Finance", "INR 1,18,000 /-"], ["Marketing", "INR 1,18,000 /-"],
             ["Business Analytics", "INR 1,18,000 /-"]]
    payload = {"spec_name": "Business Analytics", "other_specs": [
        {"other_spec_name": "Finance"}, {"other_spec_name": "Marketing"},
        {"other_spec_name": "Retail management"}, {"other_spec_name": "Agri business"}]}
    derive.apply_specialization_fees(payload, [table], "specialization")
    assert [(r["other_spec_name"], r["other_spec_fee"]) for r in payload["other_specs"]] == [
        ("Finance", "INR 1,18,000 /-"), ("Marketing", "INR 1,18,000 /-")]


def test_partner_names_written_in_a_sentence_are_not_repeated_under_the_chips():
    """SMU MBA / DSU AI: 'Deloitte, PayPal, ... are among the leading hiring partners' above the same chips."""
    chips = "<ul><li>Deloitte</li><li>PayPal</li><li>Amazon</li><li>Jio</li></ul>"
    acf = {"top_hiring_partners_course": chips,
           "placement_content": "<p>With 500+ active hiring partners, SMU offers the right opportunity.</p>"
                                "<p>Deloitte, PayPal, Amazon, and Jio are among the leading hiring partners.</p>"
                                "<p>Placement support is free. Deloitte, PayPal, Amazon and Jio hire graduates.</p>"}
    wc._dedupe_partner_list(acf, "course")
    assert acf["placement_content"] == ("<p>With 500+ active hiring partners, SMU offers the right opportunity.</p>"
                                        "<p>Placement support is free.</p>")
