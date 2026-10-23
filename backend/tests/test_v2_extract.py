"""Extraction v2: the Claude calls (request shape, refusal / truncation,
large-document split) and the SEO/hero generation. Fake client only."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pipeline.v2 import claude, extract, generate
from tests.v2_helpers import FakeAnthropic, course_answer, message, standard_client


@pytest.fixture
def one_request(monkeypatch):
    """Single-request mechanics (course pages use two requests by default)."""
    monkeypatch.setattr(extract, "_GROUPED", set())


def test_one_streaming_call_with_schema_thinking_and_fallback(one_request) -> None:
    client = standard_client()
    result = extract.extract("# Doc\n\nText", "course", "Copy of UPES Online MBA program", client=client)
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == "claude-sonnet-5-5"  # the default
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "high"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "admission_steps" in call["output_config"]["format"]["schema"]["properties"]["values"]["properties"]
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["extra_body"] == {"fallbacks": "default"}
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["max_tokens"] == 64000
    user = call["messages"][0]["content"]
    assert user.startswith("<document>\n# Doc") and "Page type: course" in user
    assert "Document title: Copy of UPES Online MBA program" in user
    assert result.values["program_name"] == "UPES Online MBA"
    assert result.usage == {"input_tokens": 20000, "output_tokens": 6000,
                            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    assert result.cost_usd == pytest.approx(20000 * 2 / 1e6 + 6000 * 10 / 1e6)


def test_model_and_effort_settings(one_request, monkeypatch) -> None:
    monkeypatch.setenv("V2_MODEL", "claude-opus-5-5")  # Opus stays selectable
    monkeypatch.setenv("V2_EFFORT", "medium")
    client = standard_client()
    result = extract.extract("x", "course", "t", model=claude.model_name(), client=client)
    assert client.calls[0]["model"] == "claude-opus-5-5"
    assert client.calls[0]["output_config"]["effort"] == "medium"
    assert result.cost_usd == pytest.approx(20000 * 4 / 1e6 + 6000 * 20 / 1e6)


def test_refusal_is_an_error_not_an_empty_page() -> None:
    client = FakeAnthropic(lambda kw: message("", stop_reason="refusal"))
    with pytest.raises(claude.ClaudeCallError) as err:
        extract.extract("x", "course", "t", client=client)
    assert err.value.reason == "refusal"


def test_cut_off_answer_is_retried_with_the_larger_output_cap(one_request) -> None:
    replies = [message('{"values": {', stop_reason="max_tokens"), message(course_answer())]
    client = FakeAnthropic(lambda kw: replies.pop(0))
    result = extract.extract("x", "course", "t", client=client)
    assert [c["max_tokens"] for c in client.calls] == [64000, 128000]
    assert result.values["program_name"] == "UPES Online MBA"
    assert result.usage["output_tokens"] == 12000  # both attempts are billed


def test_cut_off_twice_fails() -> None:
    client = FakeAnthropic(lambda kw: message("{", stop_reason="max_tokens"))
    with pytest.raises(claude.ClaudeCallError, match="cut off"):
        extract.extract("x", "course", "t", client=client)


def test_invalid_json_fails_loudly() -> None:
    client = FakeAnthropic(lambda kw: message("not json"))
    with pytest.raises(claude.ClaudeCallError) as err:
        extract.extract("x", "course", "t", client=client)
    assert err.value.reason == "bad_json"


def test_fallback_model_is_reported() -> None:
    blocks = (SimpleNamespace(type="fallback", **{"from": None, "to": None}),)
    client = FakeAnthropic(lambda kw: message(course_answer(), model="claude-opus-4-8", extra_blocks=blocks))
    result = extract.extract("x", "course", "t", client=client)
    assert result.calls[0].fallback_used is True
    assert result.calls[0].served_by == "claude-opus-4-8"


def test_large_document_is_split_at_headings_and_merged(one_request, monkeypatch) -> None:
    monkeypatch.setattr(extract, "MAX_DOC_TOKENS", 20)
    doc = "Title line\n\n## Fees\n\n" + "fee text " * 10 + "\n## FAQs\n\n" + "faq text " * 10
    answers = [
        {"values": {"total_fee": "INR 1,00,000 /-", "faqs": [{"question": "A?", "answer": "a"}], "mode": ""},
         "provenance": [{"field": "total_fee", "heading": "Fees", "confidence": "high"}], "notes": ["one"]},
        {"values": {"total_fee": "INR 2,00,000 /-", "faqs": [{"question": "B?", "answer": "b"}], "mode": "Online"},
         "provenance": [{"field": "mode", "heading": "FAQs", "confidence": "low"}], "notes": ["two"]},
    ]
    client = FakeAnthropic(lambda kw: message(answers[len(client.calls) - 1]))
    result = extract.extract(doc, "course", "Copy of X Online MBA", client=client)
    assert len(client.calls) == 2
    for call in client.calls:  # every part carries the title and the full field list
        assert "Document title: Copy of X Online MBA" in call["messages"][0]["content"]
        assert "faqs" in call["output_config"]["format"]["schema"]["properties"]["values"]["properties"]
    assert "part 1 of 2" in client.calls[0]["messages"][0]["content"]
    assert result.values["total_fee"] == "INR 1,00,000 /-"   # first filled value wins
    assert result.values["mode"] == "Online"
    assert [r["question"] for r in result.values["faqs"]] == ["A?", "B?"]
    assert result.notes == ["one", "two"]
    assert {p["field"] for p in result.provenance} == {"total_fee", "mode"}


# ── generation ──

def test_generation_fills_only_empty_fields_from_final_values() -> None:
    client = standard_client()
    payload = {"program_name": "UPES Online MBA", "university_name": "UPES Online", "seo_title": "Already set",
               "about_content": "<p>Two-year MBA.</p>", "specialization": [{"specialization_name": "Marketing"}]}
    values, call = generate.generate(payload, "course", client=client)
    assert set(values) == {"meta_description", "hero_description"}
    sent = client.calls[0]
    assert sent["output_config"]["effort"] == "medium"
    assert sorted(sent["output_config"]["format"]["schema"]["required"]) == ["hero_description", "meta_description"]
    assert '"page_name": "UPES Online MBA"' in sent["messages"][0]["content"]
    assert "Marketing" in sent["messages"][0]["content"]
    assert call.usage["input_tokens"] == 800


def test_generation_waits_for_a_page_name() -> None:
    client = standard_client()
    assert generate.generate({"about_content": "x"}, "course", client=client) == ({}, None)
    assert client.calls == []


def test_specialization_also_gets_a_certificate_line_when_missing() -> None:
    assert generate.targets({"spec_name": "DevOps"}, "specialization") == [
        "meta_description", "seo_title", "specialization_hero_description", "certificate_description"]
    assert "certificate_description" not in generate.targets(
        {"spec_name": "DevOps", "certificate_description": "From the doc."}, "specialization")


def test_hero_text_from_the_document_is_kept_and_only_missing_texts_are_written() -> None:
    from pipeline.v2.schema import extracted_fields
    assert "hero_description" in {f["key"] for f in extracted_fields("university")}
    assert "specialization_hero_description" in {f["key"] for f in extracted_fields("specialization")}
    assert "hero_description" not in generate.targets({"university_name": "UPES Online", "hero_description": "From the doc."}, "university")
    assert "hero_description" in generate.targets({"university_name": "UPES Online"}, "university")



class _GrammarTooLarge(Exception):
    status_code = 400


def test_a_schema_too_large_to_compile_is_split_into_field_groups(monkeypatch) -> None:
    """Course/specialization schemas were rejected: 'The compiled grammar is too large'."""
    monkeypatch.setattr(extract, "_GROUPED", set())
    answer = course_answer()["values"]

    def respond(kwargs):
        keys = list(kwargs["output_config"]["format"]["schema"]["properties"]["values"]["properties"])
        if len(keys) == len(answer):
            raise _GrammarTooLarge("The compiled grammar is too large, which would cause performance issues.")
        return message({"values": {k: answer[k] for k in keys},
                        "provenance": [{"field": keys[0], "heading": "H", "confidence": "high"}], "notes": [f"group of {len(keys)}"]})

    client = FakeAnthropic(respond)
    result = extract.extract("doc", "course", "t", client=client)
    assert len(client.calls) == 3          # rejected whole schema, then text fields, then lists
    assert all(extract.GROUP_NOTE in c["messages"][0]["content"] for c in client.calls[1:])
    assert result.values["program_name"] == "UPES Online MBA" and result.values["specialization"]
    assert len(result.notes) == 2 and len(result.calls) == 2
    # later documents of the same page type go straight to the groups
    client2 = FakeAnthropic(respond)
    extract.extract("doc", "course", "t", client=client2)
    assert len(client2.calls) == 2


def test_other_errors_are_not_retried(monkeypatch) -> None:
    monkeypatch.setattr(extract, "_GROUPED", set())

    def respond(kwargs):
        raise _GrammarTooLarge("invalid model")

    with pytest.raises(_GrammarTooLarge):
        extract.extract("doc", "course", "t", client=FakeAnthropic(respond))



def test_course_and_specialization_pages_use_two_requests_from_the_start() -> None:
    """Their one-request schemas are too large to compile, so no failing first attempt is made."""
    assert {"course", "specialization"} <= extract._GROUPED
    client = standard_client()
    extract.extract("doc", "specialization", "Copy of X Online MBA in Finance", client=client)
    assert len(client.calls) == 2
