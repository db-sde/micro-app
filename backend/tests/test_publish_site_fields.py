"""Publishing sends only the fields the target WordPress has: one unknown
key makes WordPress reject the whole page (staging.degreebaba.com removed
the course "validity" field; its value now goes to program_validity)."""

from __future__ import annotations

import pytest

from pipeline import wordpress_client as wc

COURSE = {"program_name": "NMIMS Online MBA", "total_fee": "INR 1,96,000 /-", "emi_amount": "INR 8,000 /-", "validity": "4 Years"}


def _publish(monkeypatch, site_fields):
    from evals.projection import FakeWordPress, _fake_site
    monkeypatch.setattr(wc, "_get_live_acf_field_types", lambda post_type: site_fields)
    fake = FakeWordPress()
    with _fake_site(fake, raw=False):
        result = wc.publish_payload(dict(COURSE), "course", status="draft")
    return fake.sent_acf(), result


@pytest.mark.usefixtures("allow_mock_transport")
def test_fields_the_site_lacks_are_not_sent(monkeypatch) -> None:
    site = {k: ["string", "null"] for k in ("program_name", "total_fee", "program_validity")}   # no emi_amount
    sent, result = _publish(monkeypatch, site)
    assert "emi_amount" not in sent
    assert sent["total_fee"] == "INR 1,96,000 /-"
    assert any("emi_amount" in w for w in result["warnings"])


@pytest.mark.usefixtures("allow_mock_transport")
def test_course_validity_goes_to_program_validity(monkeypatch) -> None:
    site = {k: ["string", "null"] for k in ("program_name", "total_fee", "emi_amount", "program_validity", "best_price_value")}
    sent, result = _publish(monkeypatch, site)
    assert sent["program_validity"] == "4 Years" and "validity" not in sent
    assert not result["warnings"]


@pytest.mark.usefixtures("allow_mock_transport")
def test_nothing_is_dropped_when_the_site_schema_cannot_be_read(monkeypatch) -> None:
    sent, _ = _publish(monkeypatch, {})
    assert sent["emi_amount"] == "₹ 8,000" and sent["total_fee"] == "INR 1,96,000 /-"


SPEC = {"spec_name": "Data Science", "total_fee": "INR 1,99,000 /-", "job_profiles": None, "examination_process": None,
        "faqs": [{"question": "Q?", "answer": "A."}], "jobs_content": None}


@pytest.mark.usefixtures("allow_mock_transport")
def test_empty_repeaters_are_left_out_not_sent_as_null(monkeypatch) -> None:
    """staging.degreebaba.com 400s the whole page on null for a repeater."""
    from evals.projection import FakeWordPress, _fake_site
    site = {"spec_name": ["string", "null"], "total_fee": ["string", "null"], "jobs_content": ["string", "null"],
            "job_profiles": ["array", "null"], "examination_process": ["array", "null"], "faqs": ["array", "null"]}
    monkeypatch.setattr(wc, "_get_live_acf_field_types", lambda post_type: site)
    fake = FakeWordPress()
    with _fake_site(fake, raw=False):
        wc.publish_payload(dict(SPEC), "specialization", status="draft")
    sent = fake.sent_acf()
    assert "job_profiles" not in sent and "examination_process" not in sent
    assert sent["faqs"] == SPEC["faqs"]
    assert "jobs_content" in sent  # a null text field is fine and still sent
