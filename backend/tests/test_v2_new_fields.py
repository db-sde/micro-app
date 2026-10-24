"""Live WordPress fields the v2 parser now fills: university placement
highlights, examination cards, EMI interest rate and partner banks; partner
banks on course and specialization pages. They must be extracted, accepted
by publish, and included in the chatbot snapshot."""

from __future__ import annotations

import pytest

from catalog.service import safe_data
from pipeline.v2.field_guide import describe
from pipeline.v2.schema import extracted_fields, output_schema

NEW = {
    "university": ["placement_highlights", "examination_cards", "emi_interest_rate_value", "partner_banks_names"],
    "course": ["partner_banks_course"],
    "specialization": ["partner_banks_specialization"],
}

VALUES = {
    "placement_highlights": "<ul><li>250+ hiring partners</li></ul>",
    "examination_cards": [{"exam_card_title": "Exam Mode", "exam_card_description": "Online proctored"}],
    "emi_interest_rate_value": "0%",
    "partner_banks_names": "<ul><li>HDFC Bank</li><li>Propelld</li></ul>",
    "partner_banks_course": "<ul><li>Axis Bank</li></ul>",
    "partner_banks_specialization": "<ul><li>ICICI Bank</li></ul>",
}


@pytest.mark.parametrize("page_type,keys", NEW.items())
def test_new_fields_are_extracted_with_a_guide_line(page_type, keys) -> None:
    extracted = {f["key"] for f in extracted_fields(page_type)}
    props = output_schema(page_type)["properties"]["values"]["properties"]
    for key in keys:
        assert key in extracted and key in props
        assert describe(page_type, key)
    if page_type == "university":
        row = props["examination_cards"]["items"]["properties"]
        assert set(row) == {"exam_card_title", "exam_card_description"}


@pytest.mark.usefixtures("allow_mock_transport")
@pytest.mark.parametrize("page_type,keys", NEW.items())
def test_publish_sends_them_to_wordpress(page_type, keys) -> None:
    from evals.projection import project
    name = {"university": "university_name", "course": "program_name", "specialization": "spec_name"}[page_type]
    payload = {name: "Test Online", **{k: VALUES[k] for k in keys}}
    sent = project(payload, page_type)["acf"]
    for key in keys:
        assert sent.get(key) == VALUES[key], key


@pytest.mark.parametrize("page_type,keys", NEW.items())
def test_chatbot_snapshot_includes_them(page_type, keys) -> None:
    data = safe_data({k: VALUES[k] for k in keys} | {"brochure": 5, "_meta": {}}, page_type)
    assert set(keys) <= set(data)
    assert "brochure" not in data and "_meta" not in data


def test_earlier_v2_fields_reach_the_chatbot_too() -> None:
    data = safe_data({"course_syllabus_description": "Intro", "top_hiring_partners_course": "IBM, KPMG"}, "course")
    assert data == {"course_syllabus_description": "Intro", "top_hiring_partners_course": "IBM, KPMG"}
