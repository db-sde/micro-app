"""Specialization-wise fee tables -> course specialization list, fee range,
and specialization pages' "other specializations" fees.

These rows used to have no field to go to, so course pages whose fee varies
by specialization showed an empty fee section and "Specializations: 0 rows".
Table shapes below are the ones docx_parser produces for the real
Shoolini / Jamia / Sharda documents.
"""

from __future__ import annotations

from pipeline.enricher import _derive_specialization_fees, collect_specialization_fees
from pipeline.kv_parser import kv_line_coverage


def table_section(rows):
    return {"content": {"intro_text": "<p>Fees by specialization.</p>", "tables": [{"data": rows}]}}


SHOOLINI = {
    "mba specialization wise fees": table_section([
        {"shoolini_university_online_mba_specializations": "Marketing Management",
         "shoolini_online_mba_fee_with_pay_after_placement_option": "INR 1,50,000 /-",
         "shoolini_online_mba_fee_without_pay_after_placement_option": "INR 1,30,000 /-"},
        {"shoolini_university_online_mba_specializations": "Retail Management",
         "shoolini_online_mba_fee_with_pay_after_placement_option": "INR 1,50,000 /-",
         "shoolini_online_mba_fee_without_pay_after_placement_option": "INR 1,30,000 /-"},
    ]),
    # A fee table without a specialization column must be ignored.
    "mba fee structure": table_section([{"year": "Year I", "fee": "INR 25,000 /-"}]),
}

SHARDA = {
    "sharda online mba specialization fees": table_section([
        {"specializations": "Marketing", "fee": "INR 25,000 /- Semester"},
        {"specializations": "Sales and Marketing", "fee": "INR 40,000 /- Semester"},
    ]),
}


def test_rows_come_only_from_tables_with_a_specialization_column():
    rows = collect_specialization_fees(SHOOLINI)
    assert [r["name"] for r in rows] == ["Marketing Management", "Retail Management"]
    assert rows[0]["fees"] == [("with pay after placement option", "INR 1,50,000 /-"),
                               ("without pay after placement option", "INR 1,30,000 /-")]


def test_course_gets_the_specialization_list_with_fees():
    payload = {"total_fee": "INR 1,30,000 /-"}
    _derive_specialization_fees(payload, SHOOLINI, "course", [])
    assert payload["specialization"][0] == {
        "specialization_name": "Marketing Management",
        "specialization_details": "INR 1,50,000 /- (with pay after placement option) · "
                                  "INR 1,30,000 /- (without pay after placement option)",
    }


def test_varying_fees_become_a_min_max_range():
    payload = {"total_fee": "Variable by specialization"}
    _derive_specialization_fees(payload, SHARDA, "course", [])
    assert payload["course_amount_range"] == "INR 25,000 /- Semester – INR 40,000 /- Semester"
    # A total with no amount is replaced by the range...
    assert payload["total_fee"] == payload["course_amount_range"]


def test_a_real_total_fee_is_kept():
    payload = {"total_fee": "INR 1,00,000 /-"}
    _derive_specialization_fees(payload, SHARDA, "course", [])
    assert payload["total_fee"] == "INR 1,00,000 /-"


def test_equal_fees_give_a_single_value_not_a_range():
    same = {"s": table_section([{"specialization": "Finance", "fee": "INR 25,000 /- (per annum)"},
                                {"specialization": "Marketing", "fee": "INR 25,000 /- (per annum)"}])}
    payload = {}
    _derive_specialization_fees(payload, same, "course", [])
    assert payload["course_amount_range"] == "INR 25,000 /- (per annum)"


def test_names_from_a_plain_list_when_there_is_no_fee_table():
    sm = {"jamia online mba specializations": {"content": [
        "The MBA is offered in three career oriented specializations:", "Finance", "Marketing", "Human Resources"]}}
    payload = {}
    _derive_specialization_fees(payload, sm, "course", [])
    assert payload["specialization"] == [{"specialization_name": n} for n in ("Finance", "Marketing", "Human Resources")]
    assert "course_amount_range" not in payload


def test_specialization_page_fills_other_specs_fees_and_its_own_fee():
    payload = {"spec_name": "Retail Management", "total_fee": None,
               "other_specs": [{"other_spec_name": "Marketing Management", "other_spec_fee": None},
                               {"other_spec_name": "Unknown Track", "other_spec_fee": None}]}
    _derive_specialization_fees(payload, SHOOLINI, "specialization", [])
    assert payload["other_specs"][0]["other_spec_fee"] == "INR 1,50,000 /-"
    assert payload["other_specs"][1]["other_spec_fee"] is None
    assert payload["total_fee"] == "INR 1,50,000 /-"


def test_kv_coverage_separates_quick_facts_from_mixed_sections():
    quick_facts = "Quick facts:\nDuration - 2 years\nMode - Online\nNAAC Grade - A\nTotal Fee - INR 1,75,000 /-"
    assert kv_line_coverage(quick_facts) >= 0.6
    mixed = ("AI FOR HUMAN RESOURCES : 1,96,000/-\nData Science : 1,80,000/-\nFintech : 1,70,000/-\n"
             "Cloud Computing : 1,90,000/-\nAICTE approved program")
    assert kv_line_coverage(mixed) < 0.6


SHARED_FEE = {
    "mba fee structure": table_section([
        {"fee_plan": "With Pay After Placement (PAP)", "amount": "INR 1,58,000", "specializations": "All Specializations"},
        {"fee_plan": "Without Pay After Placement", "amount": "INR 1,30,000", "specializations": "All Specializations"},
    ]),
}


def test_all_specializations_fee_fills_every_other_spec_with_the_lowest_fee():
    payload = {"spec_name": "Retail Management", "total_fee": "INR 1,30,000 /-",
               "other_specs": [{"other_spec_name": "Marketing Management"}, {"other_spec_name": "Digital Marketing"}]}
    _derive_specialization_fees(payload, SHARED_FEE, "specialization", [])
    assert [r["other_spec_fee"] for r in payload["other_specs"]] == ["INR 1,30,000", "INR 1,30,000"]
    assert payload["total_fee"] == "INR 1,30,000 /-"


def test_all_specializations_row_is_not_listed_as_a_specialization_on_a_course():
    payload = {"total_fee": "INR 1,30,000 /-"}
    _derive_specialization_fees(payload, SHARED_FEE, "course", [])
    assert "specialization" not in payload
    assert "course_amount_range" not in payload


def test_named_rows_still_win_over_a_shared_row():
    sm = {**SHOOLINI, **SHARED_FEE}
    payload = {"spec_name": "Retail Management",
               "other_specs": [{"other_spec_name": "Marketing Management"}, {"other_spec_name": "Banking"}]}
    _derive_specialization_fees(payload, sm, "specialization", [])
    assert [r["other_spec_fee"] for r in payload["other_specs"]] == ["INR 1,50,000 /-", "INR 1,30,000"]
