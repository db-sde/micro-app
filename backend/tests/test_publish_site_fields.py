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
    assert sent["emi_amount"] == "INR 8,000 /-" and sent["total_fee"] == "INR 1,96,000 /-"
