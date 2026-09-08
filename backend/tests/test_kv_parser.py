"""Tests for the key-value fast-path parser.

This module maps "Key - Value" lines in a document's Quick Facts block
straight onto ACF fields, bypassing embeddings. Its patterns are ordered
and first-match-wins, so an over-permissive pattern silently swallows
lines meant for a later field. That is not hypothetical: the num_programs
pattern once had every part optional, so it matched ANY key containing
the word "program" — "Program Validity" included — and program_validity
never extracted at all. The ordering/greediness tests below pin that.
"""

from __future__ import annotations

import pytest

from pipeline.kv_parser import (
    flatten_section_to_text,
    looks_like_kv_section,
    parse_kv_section,
)


def _fields(text: str) -> dict[str, object]:
    """Parse and return {field_key: value} for easier assertions."""
    return {r["field_key"]: r["value"] for r in parse_kv_section(text)}


# ──────────────────────────── section detection ────────────────────────────


def test_detects_a_quick_facts_block() -> None:
    text = "Duration - 2 years\nMode - Online\nTotal Fee - INR 1,00,000"
    assert looks_like_kv_section(text) is True


def test_rejects_prose() -> None:
    text = (
        "The university has been a pioneer in distance education for over "
        "three decades and serves more than 50,000 alumni worldwide."
    )
    assert looks_like_kv_section(text) is False


def test_rejects_a_single_kv_line() -> None:
    """One delimiter-bearing line is more likely a sentence than a block."""
    assert looks_like_kv_section("Duration - 2 years") is False


def test_rejects_a_block_that_is_mostly_prose() -> None:
    text = (
        "Duration - 2 years\n"
        "This program is designed for working professionals who want to "
        "advance their careers without pausing employment.\n"
        "Graduates go on to roles across marketing analytics and brand "
        "management in leading firms.\n"
        "Students receive mentorship throughout the academic journey.\n"
    )
    assert looks_like_kv_section(text) is False


@pytest.mark.parametrize(
    "line",
    [
        "Duration - 2 years",
        "Duration: 2 years",
        "Duration — 2 years",
        "Duration – 2 years",
    ],
)
def test_accepts_each_supported_delimiter(line: str) -> None:
    assert _fields(f"{line}\nMode - Online")["duration"] == "2 years"


# ─────────────────────── greediness / ordering regressions ───────────────────


def test_program_validity_is_not_swallowed_by_num_programs() -> None:
    """Regression: the num_programs pattern used to match any key
    containing "program", so "Program Validity" was consumed as a program
    COUNT and the validity value was lost entirely."""
    result = _fields("Program Validity - 2 years\nMode - Online")
    assert "num_programs" not in result
    assert result["validity"] == "2 years"


@pytest.mark.parametrize(
    "key",
    ["Program Fee", "Program Duration", "Program Name", "Program Validity"],
)
def test_program_prefixed_keys_do_not_become_num_programs(key: str) -> None:
    result = _fields(f"{key} - some value\nMode - Online")
    assert "num_programs" not in result, f"{key!r} was swallowed by num_programs"


@pytest.mark.parametrize(
    "key",
    ["Total Programs", "Number of Programs", "Programs Offered", "Courses Offered"],
)
def test_genuine_program_count_keys_still_map(key: str) -> None:
    result = _fields(f"{key} - 15\nMode - Online")
    assert result["num_programs"] == "15"


def test_program_name_wins_over_program_count() -> None:
    """'Program Name' is matched by an earlier, anchored pattern."""
    result = _fields("Program Name - Sharda Online MBA\nMode - Online")
    assert result["program_name"] == "Sharda Online MBA"


def test_ugc_status_key_is_not_captured_as_ugc_approved() -> None:
    result = _fields("UGC_status - Entitled\nMode - Online")
    assert result["ugc_status"] == "Entitled"
    assert "ugc_approved" not in result


def test_bare_ugc_key_maps_to_ugc_approved() -> None:
    result = _fields("UGC - Entitled\nMode - Online")
    assert result["ugc_approved"] == "Entitled"


# ───────────────────────── relationship hint capture ────────────────────────


def test_linked_university_and_course_names_are_captured() -> None:
    """Documents write the linked page's NAME (never its WordPress ID).
    These values feed relationship resolution at publish time, so losing
    them here means linked_university can never be auto-populated."""
    result = _fields(
        "Linked_university - UPES Online\nLinked_course - UPES Online MBA"
    )
    assert result["linked_university"] == "UPES Online"
    assert result["linked_course"] == "UPES Online MBA"


@pytest.mark.parametrize(
    "key", ["Linked University", "Linked_university", "linked university"]
)
def test_linked_university_key_spellings(key: str) -> None:
    result = _fields(f"{key} - UPES Online\nMode - Online")
    assert result["linked_university"] == "UPES Online"


def test_linked_program_is_an_alias_for_linked_course() -> None:
    result = _fields("Linked_program - UPES Online MBA\nMode - Online")
    assert result["linked_course"] == "UPES Online MBA"


# ────────────────────────────── value extraction ────────────────────────────


@pytest.mark.parametrize(
    ("line", "field", "expected"),
    [
        ("Established - Founded in 1985 as a trust", "established_year", "1985"),
        ("NAAC Grade - Accredited A+ by NAAC", "naac_grade", "A+"),
        ("Duration - Approximately 2 years full time", "duration", "2 years"),
        ("NIRF - Ranked #62 overall", "nirf_rank", "#62"),
        # The "/-" suffix is part of the captured amount by design.
        ("Total Fee - INR 1,00,000 /- all inclusive", "total_fee", "INR 1,00,000 /-"),
    ],
)
def test_value_extractors_pull_the_signal_out_of_prose(
    line: str, field: str, expected: str
) -> None:
    result = _fields(f"{line}\nMode - Online")
    assert result[field] == expected


def test_value_without_a_recognised_pattern_falls_back_to_raw_text() -> None:
    result = _fields("Mode - Online and distance\nDuration - 2 years")
    assert result["mode_of_learning"] == "Online and distance"


# ────────────────────────────── mode of delivery ────────────────────────────


@pytest.mark.parametrize(
    "key", ["Mode", "Mode of Learning", "Mode of Study", "Learning Mode"]
)
def test_bare_and_qualified_mode_keys_both_map(key: str) -> None:
    """Regression: only the qualified spellings used to match. A bare
    "Mode - X" line was dropped along with the consumed KV section, and
    the enricher then guessed the mode from prose instead."""
    result = _fields(f"{key} - Hybrid\nDuration - 2 years")
    assert result["mode_of_learning"] == "Hybrid"


def test_document_stated_mode_is_preserved_verbatim() -> None:
    """The stated mode must survive extraction rather than being
    re-derived — an online university's prose says "online" everywhere,
    so a guess would always win and always say Online."""
    result = _fields("Mode - Distance\nDuration - 2 years")
    assert result["mode_of_learning"] == "Distance"


@pytest.mark.parametrize("key", ["Model Number", "Moderate Fee Waiver"])
def test_words_merely_containing_mode_do_not_match(key: str) -> None:
    result = _fields(f"{key} - something\nDuration - 2 years")
    assert "mode_of_learning" not in result


def test_payment_mode_does_not_land_on_learning_mode() -> None:
    """"Mode of Payment" is a different concept from delivery mode."""
    result = _fields("Mode of Payment - Net Banking\nDuration - 2 years")
    assert "mode_of_learning" not in result


# ──────────────────────────── accreditations shape ──────────────────────────


def test_accreditations_becomes_a_repeater_not_a_string() -> None:
    """WordPress rejects a plain string for this repeater with
    "acf[accreditations][0] is not of type object", 400ing the whole
    publish — so the comma list must be split into rows here."""
    result = _fields("Approval - NAAC A+, UGC, AICTE\nMode - Online")
    assert result["accreditations"] == [
        {"body_name": "NAAC A+"},
        {"body_name": "UGC"},
        {"body_name": "AICTE"},
    ]


def test_accreditations_with_no_usable_values_is_dropped() -> None:
    result = _fields("Approval - ,,,\nMode - Online")
    assert "accreditations" not in result


# ────────────────────────────── parsing guards ──────────────────────────────


def test_faq_questions_are_not_parsed_as_metadata() -> None:
    """FAQ answers are written "Question? - Answer"; without this guard a
    question's answer overwrites a real field."""
    text = (
        "What is the duration of the program? - It is 2 years long\n"
        "Mode - Online\n"
    )
    result = _fields(text)
    assert result.get("duration") != "It is 2 years long"
    assert result["mode_of_learning"] == "Online"


def test_overly_long_keys_are_ignored() -> None:
    long_key = "Some extremely long sentence about the program duration " * 2
    result = _fields(f"{long_key} - 2 years\nMode - Online")
    assert "duration" not in result


def test_first_match_wins_for_a_repeated_field() -> None:
    result = _fields("Duration - 2 years\nDuration - 4 years")
    assert result["duration"] == "2 years"


def test_html_tags_are_stripped_from_keys_and_values() -> None:
    result = _fields("<p>Duration</p> - <strong>2 years</strong>\nMode - Online")
    assert result["duration"] == "2 years"


def test_lines_without_a_delimiter_are_skipped() -> None:
    result = _fields("Quick Facts\nDuration - 2 years\nMode - Online")
    assert result["duration"] == "2 years"


def test_every_record_carries_provenance() -> None:
    """The UI shows where each value came from; a missing source makes a
    KV-derived value indistinguishable from an LLM guess."""
    for record in parse_kv_section("Duration - 2 years\nMode - Online"):
        assert record["source"] == "kv_parser"
        assert 0 < record["confidence"] <= 1.0


# ─────────────────────────────── flattening ─────────────────────────────────


def test_flatten_handles_strings_lists_dicts_and_nesting() -> None:
    assert flatten_section_to_text("Duration - 2 years") == "Duration - 2 years"
    assert flatten_section_to_text([{"text": "Mode - Online"}]) == "Mode - Online"
    assert flatten_section_to_text(["Mode - Online"]) == "Mode - Online"
    # Table rows arrive as lists/dicts of cells and are joined into KV lines.
    assert flatten_section_to_text([["Duration", "2 years"]]) == "Duration - 2 years"
    assert flatten_section_to_text([{"key": "Duration", "value": "2 years"}]) == (
        "Duration - 2 years"
    )


def test_flatten_of_a_docx_table_feeds_the_parser() -> None:
    """Quick Facts is often a two-column table, not paragraphs."""
    content = [["Duration", "2 years"], ["Mode", "Online"]]
    text = flatten_section_to_text(content)
    assert looks_like_kv_section(text)
    assert _fields(text)["duration"] == "2 years"
