"""Extraction v2: validation checks. One case per error that reached a
published page (EXTRACTION_V2_PLAN.md §3); checks flag, they never edit.
"""

from __future__ import annotations

import pytest

from pipeline.v2 import checks
from pipeline.validator import validate_payload

DOC = """Copy of UPES Online MBA in Marketing Management

### UPES Online MBA Admission Process

Follow these steps to apply:

**Step 1. Ensure your eligibility:** Students are required to hold a bachelor's degree with 50% marks.

**Step 2. Register online:** Create an account on the UPES Online portal.

**Additional information:** Keep scanned copies of your documents ready.

### Fees

| Plan | Amount |
|---|---|
| Semester Plan | INR 45,000 /- |
| Total Fee | INR 1,80,000 /- |
"""


def codes(flags, field=None):
    return sorted({f["code"] for f in flags if field is None or f["field_key"] == field})


def run(payload, page_type="course", markdown=DOC, title="Copy of UPES Online MBA program.docx", tables=None):
    return checks.check_payload(payload, page_type, markdown, title, tables)


# ── headings ──

@pytest.mark.parametrize("text,ok", [
    ("Jamia Millia Islamia Online MBA Fee Structure", True),
    ("Why choose UPES Online?", True),
    ("AI FOR HUMAN RESOURCES : 1,96,000/-", False),
    ("National and international accreditations including AACSB, UGC, and Institute of Eminence recognition", False),
    ("The program is approved by UGC and AICTE for all learners.", False),
    ("[fee_heading] Fees", False),
])
def test_heading_format(text: str, ok: bool) -> None:
    assert checks.is_usable_heading(text) is ok


def test_fee_row_heading_is_an_error() -> None:
    flags = run({"accreditations_heading": "AI FOR HUMAN RESOURCES : 1,96,000/-"})
    assert codes(flags, "accreditations_heading") == ["heading_format"]


# ── admission ──

UPES_STEPS = ("<p>Follow these steps to apply:</p><ol>"
              "<li><strong>Step 1. Ensure your eligibility:</strong> Students are required to hold a bachelor's degree with 50% marks.</li>"
              "<li><strong>Step 2. Register online:</strong> Create an account on the UPES Online portal.</li></ol>")


def test_upes_steps_with_titles_and_note_pass() -> None:
    flags = run({"admission_steps": UPES_STEPS,
                 "admission_fee_note": "Additional information: Keep scanned copies of your documents ready."})
    assert codes(flags) == []


def test_note_that_is_a_step_is_an_error() -> None:
    flags = run({"admission_steps": UPES_STEPS, "admission_fee_note": "Step 2. Register online: Create an account on the UPES Online portal."})
    assert codes(flags, "admission_fee_note") == ["note_is_a_step"]


def test_note_listed_as_a_step_and_second_list_are_errors() -> None:
    html = UPES_STEPS.replace("</ol>", "<li>Additional information: keep copies.</li></ol>") + "<ul><li>Use the QMS.</li></ul>"
    assert codes(run({"admission_steps": html}), "admission_steps") == ["note_inside_steps", "steps_more_than_one_list"]


def test_steps_as_paragraphs_are_an_error() -> None:
    html = "<p>Step 1. Register online.</p><p>Step 2. Upload documents.</p>"
    assert codes(run({"admission_steps": html}), "admission_steps") == ["steps_not_a_list"]


# ── money and fees ──

def test_money_fields_need_an_amount() -> None:
    flags = run({"total_fee": "Variable by specialization", "emi_amount": "INR 6,927/-",
                 "fee_plans": [{"plan_name": "Semester Plan", "plan_amount": "Variable"}]},
                markdown="Semester Plan: Variable by specialization. EMI INR 6,927/-")
    assert codes(flags, "total_fee") == ["money_without_amount"]
    assert "money_without_amount" in codes(flags, "fee_plans")
    assert codes(flags, "emi_amount") == []


def test_fee_plan_rules() -> None:
    plans = [{"plan_name": "Semester Plan", "plan_amount": "INR 15,000 /-"},
             {"plan_name": "Semester Plan", "plan_amount": "INR 16,000 /-"},
             {"plan_name": "EMI Facility", "plan_amount": "INR 12,781 per month"},
             {"plan_name": "Total Fee (Pay After Placement Option)", "plan_amount": "INR 1,12,500 /-"},
             {"plan_name": "Total Fee (Without Pay After Placement Option)", "plan_amount": "INR 96,000 /-"}]
    doc = " ".join(f"{p['plan_name']} {p['plan_amount']}" for p in plans) + " Total Fee"
    flags = run({"fee_plans": plans, "total_fee": "INR 1,12,500 /-"}, markdown=doc)
    assert {"emi_as_plan", "plan_name_repeated"} <= set(codes(flags, "fee_plans"))
    assert codes(flags, "total_fee") == ["total_not_lowest_total"]
    flags = run({"fee_plans": plans[3:], "total_fee": "INR 96,000 /-"}, markdown=doc)
    assert codes(flags, "total_fee") == []


# ── names, syllabus, completeness, partners ──

def test_spec_name_must_come_from_the_title() -> None:
    # The real failure: the name was taken from the document's fee table.
    flags = run({"spec_name": "Fintech & AI"}, page_type="specialization", markdown="| Fintech & AI | INR 1,70,000 |",
                title="Copy of Jain University Online MCA in DevOps.docx")
    assert codes(flags, "spec_name") == ["name_not_from_title"]
    assert run({"spec_name": "DevOps"}, page_type="specialization", markdown="DevOps",
               title="Copy of Jain University Online MCA in DevOps.docx") == []


def test_semester_without_subjects_and_count_mismatch() -> None:
    years = [{"course_year_title": "Year I", "course_semesters": [
        {"course_semester_title": "Semester I", "course_semester_subjects": "<ul><li>A</li><li>B</li></ul>"},
        {"course_semester_title": "Semester II", "course_semester_subjects": ""}]}]
    flags = run({"course_academic_years": years, "syllabus_content": "<ul><li>A</li><li>B</li><li>C</li></ul>"},
                markdown="Year I Semester I Semester II A B C")
    assert codes(flags, "course_academic_years") == ["semester_without_subjects", "subject_count_mismatch"]


def test_programs_table_must_have_every_row() -> None:
    table = [["Program", "Fee"], ["MBA", "1"], ["MCA", "2"], ["BBA", "3"], ["BCA", "4"], ["M.Com", "5"]]
    rows = [{"program_name": n} for n in ("MBA", "MCA", "BBA", "BCA")]
    flags = run({"programs_table": rows}, page_type="university", markdown="MBA MCA BBA BCA M.Com", tables=[table])
    assert codes(flags, "programs_table") == ["rows_missing"]
    rows.append({"program_name": "M.Com"})
    assert run({"programs_table": rows}, page_type="university", markdown="MBA MCA BBA BCA M.Com", tables=[table]) == []


def test_partner_list_must_be_clean_names() -> None:
    flags = run({"top_hiring_partners_course": "Infosys, Larsen &amp; Toubro, ANZ, etc."},
                markdown="Infosys Larsen & Toubro ANZ etc")
    assert codes(flags, "top_hiring_partners_course") == ["partners_etc", "partners_markup"]


def test_guaranteed_placement_only_if_the_document_says_so() -> None:
    flags = run({"placement_content": "<p>The program offers guaranteed placement with ICICI Bank.</p>"},
                markdown="Some alumni work at ICICI Bank. The program offers placement with ICICI Bank.")
    assert codes(flags, "placement_content") == ["unsupported_claim"]


# ── grounding ──

def test_values_from_the_document_are_grounded() -> None:
    flags = run({"total_fee": "INR 1,80,000 /-", "admission_steps": UPES_STEPS})
    assert codes(flags) == []


def test_invented_numbers_and_text_are_flagged() -> None:
    flags = run({"emi_amount": "INR 8,750/month",
                 "about_content": "<p>UPES is ranked first in Asia for executive education and corporate leadership training programmes.</p>"})
    assert codes(flags, "emi_amount") == ["not_in_document"]
    assert codes(flags, "about_content") == ["not_in_document"]


def test_confidence_drops_with_flags() -> None:
    assert checks.adjusted_confidence(0.95, []) == 0.95
    assert checks.adjusted_confidence(0.95, [{"severity": "warning"}]) == 0.75
    assert checks.adjusted_confidence(0.95, [{"severity": "error"}]) == 0.3


# ── flags in the validation report ──

def test_flags_reach_the_validation_report() -> None:
    payload = {"total_fee": "Variable", "examination_process": [{"exam_process_title": "Mode", "exam_process_description": "Online"}]}
    flags = [checks.flag("total_fee", "money_without_amount", "error", "No amount")]
    report = validate_payload(payload, "specialization", flags=flags, extra_fields=["examination_process"])
    rows = {r["field_key"]: r for r in report["field_report"]}
    assert rows["total_fee"]["flags"][0]["code"] == "money_without_amount"
    assert rows["examination_process"]["status"] == "mapped"
    assert report["summary"]["flagged"] == 1


def test_report_without_flags_is_unchanged() -> None:
    payload = {"total_fee": "INR 1,30,000 /-"}
    report = validate_payload(payload, "specialization")
    assert "flagged" not in report["summary"]
    assert all("flags" not in r for r in report["field_report"])


def test_stated_count_must_match_the_list() -> None:
    rows = [{"program_name": n} for n in ("MBA", "BBA", "BCA", "PGP", "Certificate", "BCOM")]
    md = "Number of Programs: 5 MBA BBA BCA PGP Certificate BCOM"
    flags = checks.check_payload({"num_programs": "5", "programs_table": rows}, "university", md, "t")
    assert codes(flags, "num_programs") == ["count_mismatch"]
    assert checks.check_payload({"num_programs": "6+", "programs_table": rows}, "university", md + " 6+", "t") == []
    assert codes(checks.check_payload({"num_programs": "8+", "programs_table": rows}, "university", md + " 8+", "t"),
                 "num_programs") == ["count_mismatch"]


def test_own_specialization_is_not_missing_from_other_specs() -> None:
    table = [["Specializations", "Fee"], ["Marketing Management", "1"], ["Finance", "2"], ["Oil and Gas", "3"]]
    rows = [{"other_spec_name": "Finance"}, {"other_spec_name": "Oil and Gas"}]
    md = "Marketing Management Finance Oil and Gas"
    flags = checks.check_payload({"spec_name": "Marketing Management", "other_specs": rows}, "specialization", md,
                                 "Copy of UPES Online MBA in Marketing Management", [table])
    assert flags == []


def test_labels_and_generated_texts_are_not_grounded() -> None:
    payload = {"eligibility_content": [{"eligibility_title": "Educational Qualification",
                                        "eligibility_description": "A bachelor's degree with 50% marks."}],
               "certificate_description": "Learners receive a degree recognised across industries worldwide."}
    md = "A bachelor's degree with 50% marks."
    assert codes(checks.check_payload(payload, "specialization", md, "t", generated=["certificate_description"])) == []
    assert codes(checks.check_payload(payload, "specialization", md, "t")) == ["not_in_document"]
