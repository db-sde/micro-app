"""Extraction v2: deterministic steps after the model call (exact table
maths, copies, placeholder nulling, heading fallback). Tables are given
the way v2's Markdown step returns them: rows of cell text.
"""

from __future__ import annotations

from pipeline.v2 import derive
from pipeline.v2.checks import is_usable_heading

SHOOLINI_TABLE = [
    ["Shoolini University Online MBA Specializations", "Shoolini Online MBA Fee with Pay After Placement Option",
     "Shoolini Online MBA Fee without Pay After Placement Option"],
    ["Marketing Management", "INR 1,50,000 /-", "INR 1,30,000 /-"],
    ["Retail Management", "INR 1,50,000 /-", "INR 1,30,000 /-"],
]
SHARED_FEE_TABLE = [
    ["Fee Plan", "Amount", "Specializations"],
    ["With Pay After Placement (PAP)", "INR 1,58,000", "All Specializations"],
    ["Without Pay After Placement", "INR 1,30,000", "All Specializations"],
]
SHARDA_TABLE = [
    ["Specializations", "Fee"],
    ["Marketing", "INR 25,000 /- Semester"],
    ["Sales and Marketing", "INR 40,000 /- Semester"],
]


def test_course_gets_specialization_rows_with_their_fees() -> None:
    payload = {"total_fee": "INR 1,30,000 /-"}
    derive.apply_specialization_fees(payload, [SHOOLINI_TABLE], "course")
    assert payload["specialization"][0] == {
        "specialization_name": "Marketing Management",
        "specialization_details": "INR 1,50,000 /- (with pay after placement option) · "
                                  "INR 1,30,000 /- (without pay after placement option)",
    }
    assert len(payload["specialization"]) == 2


def test_varying_fees_give_a_range_and_fill_a_total_without_digits() -> None:
    payload = {"total_fee": None}
    derive.apply_specialization_fees(payload, [SHARDA_TABLE], "course")
    assert payload["course_amount_range"] == "INR 25,000 /- Semester – INR 40,000 /- Semester"
    assert payload["total_fee"] == payload["course_amount_range"]


def test_all_specializations_row_is_a_shared_fee_not_a_specialization() -> None:
    payload = {"total_fee": "INR 1,30,000 /-", "specialization": [{"specialization_name": "Finance"}]}
    derive.apply_specialization_fees(payload, [SHARED_FEE_TABLE], "course")
    assert payload["specialization"] == [{"specialization_name": "Finance"}]  # model's list kept
    assert "course_amount_range" not in payload


def test_specialization_page_other_specs_get_fees_and_shared_lowest() -> None:
    payload = {"spec_name": "Retail Management", "total_fee": None,
               "other_specs": [{"other_spec_name": "Marketing Management", "other_spec_fee": None},
                               {"other_spec_name": "Banking", "other_spec_fee": None}]}
    derive.apply_specialization_fees(payload, [SHOOLINI_TABLE, SHARED_FEE_TABLE], "specialization")
    assert [r["other_spec_fee"] for r in payload["other_specs"]] == ["INR 1,50,000 /-", "INR 1,30,000"]
    assert payload["total_fee"] == "INR 1,50,000 /-"


def test_merged_title_row_above_the_header_is_skipped() -> None:
    titled = [["Fees", "Fees", "Fees"], *SHOOLINI_TABLE]
    payload = {}
    derive.apply_specialization_fees(payload, [titled], "course")
    assert [r["specialization_name"] for r in payload["specialization"]] == ["Marketing Management", "Retail Management"]


def test_placeholders_are_null_in_fields_and_rows() -> None:
    payload = {"emi_amount": "N/A", "mode": "Online", "admission_fee_note": "-",
               "other_specs": [{"other_spec_name": "Finance", "other_spec_fee": "not available"}]}
    changes = derive.null_placeholders(payload)
    assert payload["emi_amount"] is None and payload["admission_fee_note"] is None
    assert payload["mode"] == "Online"
    assert payload["other_specs"][0]["other_spec_fee"] is None
    assert {c["field_key"] for c in changes} == {"emi_amount", "admission_fee_note", "other_specs"}


VALID = {"program_name", "fee_heading", "fee_plans", "faqs_heading", "faqs", "accreditations_heading",
         "course_accreditations", "syllabus_heading", "syllabus_content"}


def test_heading_fallback_only_for_sections_with_content() -> None:
    payload = {"program_name": "Jamia Online MBA", "fee_heading": None, "fee_plans": [{"plan_name": "Total Fee"}],
               "faqs_heading": None, "faqs": None}
    changes = derive.apply_heading_fallbacks(payload, "course", VALID, is_usable_heading)
    assert payload["fee_heading"] == "Jamia Online MBA Fee Structure"
    assert payload["faqs_heading"] is None  # no FAQ content, nothing to title
    assert [c["rule"] for c in changes] == ["heading_fallback"]


def test_a_fee_row_heading_is_replaced_and_a_real_heading_kept() -> None:
    payload = {"program_name": "Jain University Online MBA",
               "accreditations_heading": "AI FOR HUMAN RESOURCES : 1,96,000/-",
               "course_accreditations": [{"course_body_name": "UGC"}],
               "syllabus_heading": "Jain Online MBA Syllabus", "syllabus_content": "<ul><li>A</li></ul>"}
    derive.apply_heading_fallbacks(payload, "course", VALID, is_usable_heading)
    assert payload["accreditations_heading"] == "Jain University Online MBA Accreditations"
    assert payload["syllabus_heading"] == "Jain Online MBA Syllabus"


def test_copies_for_fields_wordpress_shows_twice() -> None:
    payload = {"syllabus_heading": "MBA Syllabus", "emi_amount": "INR 10,156/-",
               "eligibility_content": [{"eligibility_title": "Degree", "eligibility_description":
                                        "Must have a bachelor's degree from a UGC-recognized university. Final-year students may apply."}]}
    derive.apply_copies(payload, "specialization")
    assert payload["syllabus_section_heading"] == "MBA Syllabus"
    assert payload["specialization_lowest_emi_strats_from"] == "10,156"
    assert payload["eligibility_summary"] == "Must have a bachelor's degree from a UGC-recognized university."


def test_copies_never_overwrite_extracted_values() -> None:
    payload = {"syllabus_heading": "MBA Syllabus", "course_syllabus_section_heading": "Curriculum",
               "eligibility_summary": "Graduates may apply."}
    derive.apply_copies(payload, "course")
    assert payload["course_syllabus_section_heading"] == "Curriculum"
    assert payload["eligibility_summary"] == "Graduates may apply."
