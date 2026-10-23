"""Job-roles paragraph (specialization jobs_content) and hiring partners
(top_hiring_partners_course / hiring_partners_specialization).

Both WordPress fields existed but were never filled: the job section kept
only its table rows, and partner names stayed buried in placement_content,
so the placement box showed only its intro. Inputs mirror real stored
payloads (UPES, Jain, OP Jindal) and docx_parser output.
"""

from __future__ import annotations

from pipeline import wordpress_client as wc
from pipeline.enricher import _derive_jobs_intro

UPES = ("<p>UPES has strong ties to leading MNCs.</p><p>Some of the major active hiring partners of UPES Online MBA graduates are:</p>"
        "<p>IBM</p><p>KPMG</p><p>Larsen &amp; Tourbo</p><p>Adecco, etc</p>")


def test_partners_after_a_lead_in_line():
    acf = {"placement_content": UPES}
    extras = wc._placement_extras(acf, "specialization")
    assert extras == {"hiring_partners_specialization": "IBM, KPMG, Larsen & Tourbo, Adecco"}
    assert acf["placement_content"].endswith(
        "<ul><li>IBM</li><li>KPMG</li><li>Larsen &amp; Tourbo</li><li>Adecco</li></ul>")
    assert acf["placement_content"].startswith("<p>UPES has strong ties")


def test_partners_written_inline_in_a_sentence():
    """Jain: "... top hiring corporates ... include Infosys, Honeywell, Hitachi, etc." """
    html = ("<p>The top hiring corporates of the Jain University online MCA course include Infosys, Honeywell, "
            "Hitachi, Johnson Controls, ICICI Bank, etc.</p><p>Placement services include:</p>"
            "<p>Professional resumes.</p><p>Interview preparation guide.</p>")
    acf = {"placement_content": html}
    assert wc._placement_extras(acf, "course") == {
        "top_hiring_partners_course": "Infosys, Honeywell, Hitachi, Johnson Controls, ICICI Bank"}
    assert acf["placement_content"] == html  # inline form: content left as written


def test_a_list_of_services_is_not_partners():
    html = "<p>The placement services provided by them include:</p><p>Professional resumes.</p><p>Interview preparation guide.</p>"
    assert wc._placement_extras({"placement_content": html}, "specialization") == {}


def test_organizations_where_alumni_work():
    """OP Jindal phrases it this way (it explicitly doesn't guarantee placement)."""
    html = ("<p>Some of the major organizations where the alumni of the program work are listed below:</p>"
            "<p>ICICI Bank</p><p>ITC</p><p>ANZ, etc.</p>")
    assert wc._placement_extras({"placement_content": html}, "course") == {
        "top_hiring_partners_course": "ICICI Bank, ITC, ANZ"}


def test_university_pages_have_no_partner_field():
    assert wc._placement_extras({"placement_content": UPES}, "university") == {}


def _job_section(heading="upes online mba job opportunities", cols=("job_profiles", "average_salary")):
    return {heading: {"content": {
        "intro_text": "<p>Marketing budgets are rising.</p><p>A few suitable job profiles are listed below.</p>",
        "tables": [{"data": [{cols[0]: "Marketing Manager", cols[1]: "INR 6 LPA"}]}]}}}


def test_job_section_intro_becomes_jobs_content():
    payload = {}
    _derive_jobs_intro(payload, _job_section(), "specialization", [])
    assert payload["jobs_content"] == "Marketing budgets are rising.\n\nA few suitable job profiles are listed below."


def test_job_table_is_recognised_even_under_another_heading():
    payload = {}
    _derive_jobs_intro(payload, _job_section("career prospects", ("job_prospects", "average_salary")), "specialization", [])
    assert payload["jobs_content"].startswith("Marketing budgets")


def test_no_job_section_means_no_jobs_content():
    sm = {"specialization fee": {"content": {"intro_text": "<p>Fees.</p>",
                                            "tables": [{"data": [{"specialization": "AI", "fee": "INR 1,00,000"}]}]}}}
    payload = {}
    _derive_jobs_intro(payload, sm, "specialization", [])
    assert "jobs_content" not in payload


def test_jobs_content_only_for_specialization_pages():
    payload = {}
    _derive_jobs_intro(payload, _job_section(), "course", [])
    assert "jobs_content" not in payload
