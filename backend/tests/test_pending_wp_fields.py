"""Section paragraphs the WordPress team is adding (accreditation_paragraph,
eligibility_criteria_paragraph, fee_structure_paragraph, ...). Sending a
field WordPress doesn't have 400s the whole page, so each one goes out only
once the live schema lists it."""

from __future__ import annotations

import pytest

from pipeline import wordpress_client as wc
from pipeline.v2.field_guide import describe
from pipeline.v2.run import extra_report_fields
from pipeline.v2.schema import extracted_fields

COURSE = {
    "program_name": "NMIMS Online MBA",
    "accreditations_intro": "NMIMS Online is accredited by apex bodies, such as:",
    "eligibility_intro": "Applicants must meet the criteria below.",
    "fee_intro": "The fee can be paid per semester or at once.",
    "jobs_intro": "Graduates can take up these roles:",
    "course_syllabus_description": "The MBA has four semesters.",
    "validity": "Lifetime",
}
SPEC = {
    "spec_name": "Marketing Management",
    "eligibility_intro": "Applicants must meet the criteria below.",
    "fee_intro": "The fee for this specialization is:",
    "jobs_content": "Marketing graduates can work as:",
    "other_specs_intro": "UPES also offers these specializations:",
    "syllabus_description": "The syllabus covers four semesters.",
}
EXPECTED = {
    "course": {
        "accreditation_paragraph": COURSE["accreditations_intro"],
        "eligibility_criteria_paragraph": COURSE["eligibility_intro"],
        "fee_structure_paragraph": COURSE["fee_intro"],
        "job_roles_&_salary_paragraph": COURSE["jobs_intro"],
        "syllabus_section_paragraph": COURSE["course_syllabus_description"],
        "program_validity": COURSE["validity"],
    },
    "specialization": {
        "eligibility_criteria_paragraph": SPEC["eligibility_intro"],
        "fee_section_paragraph": SPEC["fee_intro"],
        "job_profiles_section_paragraph": SPEC["jobs_content"],
        "other_specializations_section_paragraph": SPEC["other_specs_intro"],
        "syllabus_section_paragraph": SPEC["syllabus_description"],
    },
}
PAYLOADS = {"course": COURSE, "specialization": SPEC}


def _sent(page_type, live_extra, monkeypatch):
    from evals.projection import project
    real = wc._get_live_acf_field_types

    def live(post_type):
        types = dict(real(post_type))  # the fake site's snapshot
        types.update({k: ["string", "null"] for k in live_extra})
        return types

    monkeypatch.setattr(wc, "_get_live_acf_field_types", live)
    return project(dict(PAYLOADS[page_type]), page_type)["acf"]


@pytest.mark.usefixtures("allow_mock_transport")
@pytest.mark.parametrize("page_type", ["course", "specialization"])
def test_not_sent_while_wordpress_lacks_the_fields(page_type, monkeypatch) -> None:
    sent = _sent(page_type, [], monkeypatch)
    assert not set(EXPECTED[page_type]) & set(sent)


@pytest.mark.usefixtures("allow_mock_transport")
@pytest.mark.parametrize("page_type", ["course", "specialization"])
def test_sent_once_wordpress_has_them(page_type, monkeypatch) -> None:
    sent = _sent(page_type, list(EXPECTED[page_type]), monkeypatch)
    for wp_key, value in EXPECTED[page_type].items():
        assert sent.get(wp_key) == value, wp_key
    # the copies keep going to their existing fields too
    if page_type == "specialization":
        assert sent["jobs_content"] == SPEC["jobs_content"]
        assert sent["syllabus_description"] == SPEC["syllabus_description"]
    else:
        assert sent["course_syllabus_description"] == COURSE["course_syllabus_description"]


@pytest.mark.usefixtures("allow_mock_transport")
def test_only_the_fields_wordpress_has_are_sent(monkeypatch) -> None:
    sent = _sent("course", ["fee_structure_paragraph"], monkeypatch)
    assert sent["fee_structure_paragraph"] == COURSE["fee_intro"]
    assert "accreditation_paragraph" not in sent and "eligibility_criteria_paragraph" not in sent


def test_other_specs_intro_is_extracted_and_shown_in_the_app() -> None:
    assert "other_specs_intro" in {f["key"] for f in extracted_fields("specialization")}
    assert describe("specialization", "other_specs_intro")
    for page_type, keys in {"course": ["eligibility_intro", "fee_intro", "accreditations_intro", "jobs_intro"],
                            "specialization": ["eligibility_intro", "fee_intro", "other_specs_intro"]}.items():
        assert set(keys) <= set(extra_report_fields(page_type))
