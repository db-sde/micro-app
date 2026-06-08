"""
Generic key-value metadata section parser.

Some documents embed a "details" or "info" section with key-value pairs
that contain data for *multiple* ACF fields in a single section, e.g.:

    Approval - UGC, NAAC A+, AICTE
    Established year - 1998
    Mode of Learning - Online, distance, and on-campus.
    Total Students - 85,000+

If the pipeline tries to match this section to one field it will fail.
This module detects such sections, parses them line-by-line, and maps
each key-value pair directly to the correct ACF field — bypassing the
embedding+LLM path entirely.

All patterns are **semantic** (based on meaning), not institution-specific.
Works for any institution, course, or specialization.

Public API
----------
looks_like_kv_section(raw_text)  → bool
parse_kv_section(raw_text)       → list[dict]   (field_key, value, confidence, source)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("degreebaba.kv_parser")

# ──────────────────────────── KV delimiter ────────────────────────────

# Accepts: " - ", " : ", " — ", " – ", " : ", ": ", "- " etc.
KV_DELIMITER_RE = re.compile(r"\s*[-:—–]\s+")


def looks_like_kv_section(raw_text: str) -> bool:
    """Return True if *raw_text* looks like a key-value metadata block.

    Generic heuristic: ≥ 2 lines that contain a delimiter and are
    short enough to be a key-value pair (not a sentence or paragraph).
    Works for any institution.
    """
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    if len(lines) < 2:
        return False

    kv_count = sum(
        1
        for line in lines
        if KV_DELIMITER_RE.search(line) and 4 < len(line) < 250
    )
    # Require at least 2 KV pairs AND > 50 % of non-empty lines are KV
    return kv_count >= 2 and kv_count / len(lines) >= 0.5


# ──────────────────────────── semantic key map ────────────────────────────

# Maps regex on key text → ACF field key.
# Each pattern is a SEMANTIC concept, not institution-specific wording.
# Ordered: more specific patterns first.
_KV_FIELD_MAP: list[tuple[str, str]] = [
    # University Full Name
    (r"university\s*full\s*name|full\s*name", "university_full_name"),
    # CDOE Year
    (r"cdoe(?:\s*year)?", "cdoe_year"),
    # UGC Approval specifically
    (r"ugc", "ugc_approved"),
    # NAAC grade specifically
    (r"naac\s*(?:grade|rating|score)?|grade", "naac_grade"),
    # Approvals / accreditations (excluding UGC/NAAC which are caught above)
    (r"approval|aicte|recogni|accredit|certif", "accreditations"),
    # Establishment
    (r"establish|found(?:ed|ing)|inception|since\s*(?:19|20)\d{2}",
                                                              "established_year"),
    # Mode of delivery
    (r"mode\s*(?:of\s*)?(?:learning|study|education|delivery|teaching)",
                                                              "mode_of_learning"),
    # Program count stat
    (r"(?:total\s*|number\s*of\s*)?(?:programs?|courses?)(?:\s*(?:offered|available|count))?",
                                                              "num_programs"),
    # NAAC grade specifically
    (r"naac\s*(?:grade|rating|score)|grade",                  "naac_grade"),
    # Ranking
    (r"rank(?:ing|ed)?|nirf|rated\s+\d",                      "ranking"),
    # Campus / location
    (r"campus(?:es)?|location(?:s)?|headquarter|head\s*office",
                                                              "campus_location"),
    # Starting fee
    (r"starting\s*fee",                                       "starting_fee"),
    # Fee / cost
    (r"(?:total\s*)?(?:course|program)?\s*fee(?:s)?|total\s*cost|tuition",
                                                              "total_fee"),
    # Duration
    (r"duration|program\s*length|course\s*(?:length|period)|time\s*to\s*complete",
                                                              "duration"),
    # EMI
    (r"emi|monthly\s*(?:installment|payment)|pay\s*per\s*month",
                                                              "emi_amount"),
    # Lateral entry / eligibility shortcuts
    (r"eligib|who\s*can\s*apply|qualif",                      "eligibility"),
    # Exam / assessment
    (r"exam(?:ination)?|assessment|evaluation|grading",       "exam_pattern"),
    # Specializations count (stat)
    (r"(?:total\s*|number\s*of\s*)?specialization(?:s)?(?:\s*(?:offered|count|available))?",
                                                              "num_specializations"),
]

# Optional value extractors for fields where we can do better than raw text
_VALUE_EXTRACTORS: dict[str, re.Pattern[str]] = {
    "established_year": re.compile(r"\b(19|20)\d{2}\b"),
    "naac_grade":       re.compile(r"\b[A-F]\+?\b"),
    "total_fee":        re.compile(r"(?:INR|₹|Rs\.?)\s*[\d,]+(?:\s*/\-)?"),
    "duration":         re.compile(r"\d+\s*(?:year|month|semester)s?", re.IGNORECASE),
    "emi_amount":       re.compile(r"(?:INR|₹|Rs\.?)\s*[\d,]+", re.IGNORECASE),
    "num_programs":         re.compile(r"\d+\s*\+?"),
    "num_specializations":  re.compile(r"\d+\s*\+?"),
}


def parse_kv_section(raw_text: str) -> list[dict[str, Any]]:
    """Parse a key-value metadata block into ACF field assignments.

    Generic — no institution-specific logic.

    Parameters
    ----------
    raw_text : str
        Section content as a plain text string (may include ``\\n``).

    Returns
    -------
    list[dict]
        Each entry has ``field_key``, ``value``, ``confidence``, ``source``.
        Only lines that match a known semantic pattern are returned.
    """
    lines = [l.strip() for l in raw_text.split("\n") if l.strip()]
    results: list[dict[str, Any]] = []
    seen_fields: set[str] = set()

    for line in lines:
        parts = KV_DELIMITER_RE.split(line, maxsplit=1)
        if len(parts) != 2:
            continue

        key_text   = parts[0].strip()
        value_text = parts[1].strip()

        if not key_text or not value_text:
            continue

        # Match key text against semantic patterns
        matched_field: str | None = None
        for pattern, field_key in _KV_FIELD_MAP:
            if re.search(pattern, key_text, re.IGNORECASE):
                matched_field = field_key
                break

        if not matched_field:
            continue

        # Skip duplicate field assignments (keep first match)
        if matched_field in seen_fields:
            continue
        seen_fields.add(matched_field)

        # Apply value extractor if available for more precise extraction
        if matched_field in _VALUE_EXTRACTORS:
            m = _VALUE_EXTRACTORS[matched_field].search(value_text)
            if m:
                value_text = m.group(0).strip()

        results.append({
            "field_key":  matched_field,
            "value":      value_text,
            "confidence": 0.90,
            "source":     "kv_parser",
        })
        logger.info(
            "KV_PARSED: key=%r → field=%s value=%r",
            key_text, matched_field, value_text,
        )

    return results


def flatten_section_to_text(content: Any) -> str:
    """Convert section content (any type) to a plain-text string for KV detection."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    parts.append(str(text))
                else:
                    parts.extend(str(v) for v in item.values() if v)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    if isinstance(content, dict):
        return "\n".join(str(v) for v in content.values() if v)
    return str(content)
