"""Publish-time clean-up of extracted content (pipeline/wordpress_client).

Each case is taken from a page the team reviewed on the live WordPress
site, using the payload the parser had actually stored for it.
"""

from __future__ import annotations

from pipeline import wordpress_client as wc
from pipeline.enricher import specialization_from_title, summarize_eligibility


def polish(acf, page_type="course"):
    return wc._polish_for_wordpress(dict(acf), page_type)


def test_placeholders_are_not_published():
    out = polish({"emi_amount": "NA", "admission_fee_note": "N/A", "mode": "Online"})
    assert out["emi_amount"] is None and out["admission_fee_note"] is None and out["mode"] == "Online"


def test_content_does_not_repeat_its_section_heading():
    out = polish({"exam_content": "<h3>Jain Examination Process</h3><p>Exams are online.</p>"}, "university")
    assert out["exam_content"] == "<p>Exams are online.</p>"


def test_a_fee_row_cannot_become_a_heading():
    """Jain course: accreditations heading was "AI FOR HUMAN RESOURCES : 1,96,000/-"."""
    out = polish({"program_name": "Jain University Online MBA", "accreditations_heading": "AI FOR HUMAN RESOURCES : 1,96,000/-"})
    assert out["accreditations_heading"] == "Jain University Online MBA Accreditations"


def test_a_sentence_cannot_become_a_heading():
    long = "National and international accreditations including AACSB, UGC, and Institute of Eminence recognition"
    out = polish({"program_name": "OP Jindal Online BBA", "accreditations_heading": long})
    assert out["accreditations_heading"] == "OP Jindal Online BBA Accreditations"


def test_normal_headings_are_untouched():
    out = polish({"program_name": "X", "fee_heading": "Jamia Millia Islamia Online MBA Fee Structure"})
    assert out["fee_heading"] == "Jamia Millia Islamia Online MBA Fee Structure"


def test_the_note_is_never_just_one_of_the_steps():
    steps = "<ol><li><strong>Step 4.</strong> Make the payment and submit the form.</li></ol>"
    out = polish({"admission_steps": steps, "admission_fee_note": "Step 4. Make the payment and submit the form."}, "university")
    assert out["admission_fee_note"] is None


def test_a_genuine_note_is_kept():
    out = polish({"admission_steps": "<ol><li>Apply online.</li></ol>",
                  "admission_fee_note": "To secure a seat, pay the program fee."}, "university")
    assert out["admission_fee_note"] == "To secure a seat, pay the program fee."


def test_later_lists_become_the_note_instead_of_extra_steps():
    """Jain university: "Important instructions" were numbered as steps 7 and 8."""
    html = ("<p>Follow these steps:</p><ol><li>Register.</li><li>Pay.</li></ol>"
            "<p><strong>Important instructions:</strong></p><ul><li>Use an active e-mail ID.</li><li>Use the QMS for queries.</li></ul>")
    out = polish({"admission_steps": html, "admission_fee_note": "Step 2. Pay."}, "university")
    assert out["admission_steps"] == "<p>Follow these steps:</p><ol><li>Register.</li><li>Pay.</li></ol>"
    assert out["admission_fee_note"] == "Use an active e-mail ID. Use the QMS for queries."


def test_steps_written_as_paragraphs_become_a_list():
    """UPES: steps written as plain paragraphs showed as "No steps"."""
    html = "<p>Follow the process:</p><p>Step 1. Register online.</p><p>Step 2. Upload documents.</p>"
    out = polish({"admission_steps": html}, "university")
    assert out["admission_steps"] == "<p>Follow the process:</p><ol><li>Step 1. Register online.</li><li>Step 2. Upload documents.</li></ol>"


def test_truncated_eligibility_note_is_rebuilt():
    out = polish({
        "eligibility_summary": "Educational Qualification Bachelor's degree in any stream from a recognized university...",
        "eligibility_content": [{"eligibility_title": "Educational Qualification",
                                 "eligibility_description": "Bachelor's degree in any stream from a recognized university"}],
    })
    assert out["eligibility_summary"] == "Bachelor's degree in any stream from a recognized university."


def test_total_row_is_the_total_fee():
    """Jamia: total_fee had picked up Year I (30,000) instead of the 60,000 total."""
    plans = [{"plan_name": "Year I", "plan_amount": "INR 30,000 /-"}, {"plan_name": "Year II", "plan_amount": "INR 30,000 /-"},
             {"plan_name": "Total Fee", "plan_amount": "INR 60,000 /-"}]
    assert polish({"total_fee": "INR 30,000 /-", "fee_plans": plans})["total_fee"] == "INR 60,000 /-"


def test_fee_rows_without_an_amount_or_for_emi_are_dropped():
    """Jain: four "Variable by specialization" cards and an EMI card."""
    plans = [{"plan_name": "Semester I", "plan_amount": "Variable by specialization"},
             {"plan_name": "Semester II", "plan_amount": None},
             {"plan_name": "EMI Facility", "plan_amount": "INR 12,781 per month"},
             {"plan_name": "Semester Plan", "plan_amount": "INR 45,000"}]
    assert polish({"fee_plans": plans})["fee_plans"] == [{"plan_name": "Semester Plan", "plan_amount": "INR 45,000"}]


def test_syllabus_intro_goes_to_the_field_wordpress_displays():
    html = "<p>The syllabus spans 4 semesters.</p><h3>Year I</h3><h4>Semester I</h4><ul><li>Accounting</li></ul>"
    extras = wc._syllabus_extras({"syllabus_content": html, "syllabus_heading": "MBA Syllabus"}, "course")
    assert extras == {"course_syllabus_description": "The syllabus spans 4 semesters.",
                      "course_syllabus_section_heading": "MBA Syllabus"}
    extras = wc._syllabus_extras({"syllabus_content": html}, "specialization")
    assert extras == {"syllabus_description": "The syllabus spans 4 semesters."}


def test_university_pages_have_no_syllabus_extras():
    assert wc._syllabus_extras({"syllabus_content": "<p>x</p>"}, "university") == {}


def test_specialization_name_comes_from_the_title():
    assert specialization_from_title("Copy of Jain University Online MCA in DevOps.docx") == "DevOps"
    assert specialization_from_title("Copy of Shoolini University Online MBA in Retail Management.docx") == "Retail Management"
    assert specialization_from_title("Sharda Online MBA program.docx") is None


def test_eligibility_summary_is_a_whole_sentence():
    rows = [{"eligibility_title": "Bachelor's Degree", "eligibility_description":
             "Must have a bachelor's degree from a UGC-recognized university. Final-year students may apply."}]
    assert summarize_eligibility(rows) == "Must have a bachelor's degree from a UGC-recognized university."


def test_repeated_plan_names_get_their_option_and_lowest_total_wins():
    # Shoolini BBA: a "with / without Pay After Placement" two-column table.
    plans = [
        {"plan_name": "Semester Plan", "plan_amount": "INR 15,000 /-", "plan_total": "Pay After Placement Option"},
        {"plan_name": "Semester Plan", "plan_amount": "INR 16,000 /-", "plan_total": "Without Pay After Placement Option"},
        {"plan_name": "Pay After Placement", "plan_amount": "INR 22,500 /-", "plan_total": "Pay After Placement Option"},
        {"plan_name": "Total Fee", "plan_amount": "INR 1,12,500 /-", "plan_total": "Pay After Placement Option"},
        {"plan_name": "Total Fee", "plan_amount": "INR 96,000 /-", "plan_total": "Without Pay After Placement Option"},
    ]
    out = polish({"fee_plans": plans})
    assert [r["plan_name"] for r in out["fee_plans"]] == [
        "Semester Plan (Pay After Placement Option)",
        "Semester Plan (Without Pay After Placement Option)",
        "Pay After Placement",
        "Total Fee (Pay After Placement Option)",
        "Total Fee (Without Pay After Placement Option)",
    ]
    assert out["total_fee"] == "INR 96,000 /-"
    assert plans[0]["plan_name"] == "Semester Plan"  # the stored payload isn't changed
