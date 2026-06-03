"""
Regex-based payload enrichment — extracts nested stat values from
already-extracted sections WITHOUT any AI/API calls.

This module runs as a post-processing stage after the main extraction
pipeline.  It fills in missing stat fields (duration, total_fee, emi_amount,
etc.) by scanning related sections and payload values with deterministic
regex patterns.

Public API
----------
enrich_payload(payload, section_map, page_type)
    Post-processes the payload to fill in missing stat fields.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("degreebaba.enricher")

# ────────────────────────── HTML helper ──────────────────────────

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    return _HTML_TAG_RE.sub(" ", text)


# ────────────────────────── regex patterns ──────────────────────────

# Duration patterns — ordered by specificity (most specific first)
_DURATION_PATTERNS = [
    # Explicit label:  "Duration: 2 Years"  "Program Duration – 24 Months"
    re.compile(
        r"(?:course\s+)?duration\s*[:\-–]\s*(\d+)\s*[-–]?\s*"
        r"(?:year|years|yr|yrs|month|months|mo|mos)\b",
        re.IGNORECASE,
    ),
    # Inline:  "2 Year Program"  "2-Year Course"  "2 Years"
    re.compile(
        r"(\d+)\s*[-–]?\s*(?:year|years|yr|yrs)"
        r"(?:\s+(?:program|course|degree|duration))?\b",
        re.IGNORECASE,
    ),
    # Month variant:  "24 Months"  "18 Month Program"
    re.compile(
        r"(\d+)\s*[-–]?\s*(?:month|months|mo|mos)"
        r"(?:\s+(?:program|course|degree|duration))?\b",
        re.IGNORECASE,
    ),
]

# Currency prefix:  ₹  INR  Rs.  Rs
_CURRENCY_PREFIX = r"(?:₹|INR|Rs\.?)\s*"

# Indian / international number:  1,00,000  100,000  100000
_NUMBER = r"[\d,]+"

# Fee patterns — specific labels first
_FEE_SPECIFIC_PATTERNS = [
    # "Total Fee: ₹1,00,000"  "Total Course Fee – INR 98,000"
    re.compile(
        r"total\s*(?:course\s+)?(?:fee|cost|amount)\s*[:\-–]\s*"
        + _CURRENCY_PREFIX + r"(" + _NUMBER + r")",
        re.IGNORECASE,
    ),
    # "Course Fee: ₹98,000"  "Program Fee ₹98000"
    re.compile(
        r"(?:course|program|full)\s*fee\s*[:\-–]?\s*"
        + _CURRENCY_PREFIX + r"(" + _NUMBER + r")",
        re.IGNORECASE,
    ),
    # "Fee: ₹98,000"  (generic fee label)
    re.compile(
        r"\bfee\s*[:\-–]\s*" + _CURRENCY_PREFIX + r"(" + _NUMBER + r")",
        re.IGNORECASE,
    ),
]

# EMI patterns
_EMI_PATTERNS = [
    # "EMI Starts From ₹5725"  "EMI: ₹5,725"
    re.compile(
        r"emi\s*(?:starts?\s*(?:from|at))?\s*[:\-–]?\s*"
        + _CURRENCY_PREFIX + r"(" + _NUMBER + r")",
        re.IGNORECASE,
    ),
    # "₹5725/month"  "₹5,725 per month"
    re.compile(
        _CURRENCY_PREFIX + r"(" + _NUMBER + r")\s*/?\s*(?:per\s*)?month\b",
        re.IGNORECASE,
    ),
    # "5725 per month"  (no currency prefix)
    re.compile(
        r"(" + _NUMBER + r")\s*(?:per|/)\s*month\b",
        re.IGNORECASE,
    ),
]

# Generic currency pattern — used as fallback for fee detection
_GENERIC_CURRENCY_RE = re.compile(
    _CURRENCY_PREFIX + r"(" + _NUMBER + r")", re.IGNORECASE
)

# ────────────────────────── enrichment rules ──────────────────────────

# page_type → target_field → {payload sources, heading keywords, extractor}
_ENRICHMENT_MAP: dict[str, dict[str, dict[str, Any]]] = {
    "course": {
        "duration": {
            "payload_sources": [
                "course_facts", "course_about", "fee_structure",
                "eligibility", "admission_process",
            ],
            "heading_keywords": [
                "fact", "detail", "about", "duration", "overview", "highlight",
            ],
            "extractor": "duration",
        },
        "total_fee": {
            "payload_sources": [
                "fee_structure", "specialization_fees",
                "course_facts", "emi_details",
            ],
            "heading_keywords": ["fee", "cost", "price", "payment"],
            "extractor": "fee",
        },
        "emi_amount": {
            "payload_sources": [
                "fee_structure", "emi_details", "course_facts",
            ],
            "heading_keywords": ["emi", "installment", "payment", "fee"],
            "extractor": "emi",
        },
    },
    "specialization": {
        "spec_total_fee": {
            "payload_sources": [
                "spec_fee_table", "emi_details", "spec_facts",
            ],
            "heading_keywords": ["fee", "cost", "price", "payment"],
            "extractor": "fee",
        },
        "spec_emi": {
            "payload_sources": [
                "spec_fee_table", "emi_details", "spec_facts",
            ],
            "heading_keywords": ["emi", "installment", "payment", "fee"],
            "extractor": "emi",
        },
    },
}


# ────────────────────────── public API ──────────────────────────


def enrich_payload(
    payload: dict[str, Any],
    section_map: dict[str, dict[str, Any]],
    page_type: str,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Post-process the payload to fill missing stat fields via regex.

    Scans already-extracted payload values and raw section content using
    deterministic regex patterns.  **No API calls.**

    Parameters
    ----------
    payload : dict
        Current extraction payload (modified in place).
    section_map : dict
        Original section map from ``parse_docx``.
    page_type : str
        One of ``"university"``, ``"course"``, ``"specialization"``.

    Returns
    -------
    tuple[dict, list[dict]]
        ``(enriched_payload, enrichment_log)`` where each log entry
        has ``field_key``, ``status``, and ``source``.
    """
    rules = _ENRICHMENT_MAP.get(page_type, {})
    if not rules:
        return payload, []

    enrichment_log: list[dict[str, str]] = []

    for target_field, rule in rules.items():
        # Skip if field already has a non-None value
        if payload.get(target_field) is not None:
            enrichment_log.append({
                "field_key": target_field,
                "status": "already_present",
                "source": "original_extraction",
            })
            continue

        extractor_fn = _EXTRACTORS[rule["extractor"]]
        found_value: str | None = None
        found_source: str | None = None

        # Strategy 1: Search within already-extracted payload values
        for source_key in rule["payload_sources"]:
            source_value = payload.get(source_key)
            if source_value is None:
                continue
            flat_text = _flatten_value(source_value)
            result = extractor_fn(flat_text)
            if result:
                found_value = result
                found_source = f"payload:{source_key}"
                break

        # Strategy 2: Search raw section_map by heading keyword
        if found_value is None:
            for heading, section in section_map.items():
                if heading.startswith("__"):
                    continue
                heading_lower = heading.lower()
                if any(kw in heading_lower for kw in rule["heading_keywords"]):
                    flat_text = _flatten_section_content(
                        section.get("content", "")
                    )
                    result = extractor_fn(flat_text)
                    if result:
                        found_value = result
                        found_source = f"section:{heading}"
                        break

        # Strategy 3: Scan ALL sections (last resort)
        if found_value is None:
            for heading, section in section_map.items():
                if heading.startswith("__"):
                    continue
                flat_text = _flatten_section_content(
                    section.get("content", "")
                )
                result = extractor_fn(flat_text)
                if result:
                    found_value = result
                    found_source = f"full_scan:{heading}"
                    break

        if found_value:
            payload[target_field] = found_value
            enrichment_log.append({
                "field_key": target_field,
                "status": "enriched",
                "source": found_source,
            })
            logger.info(
                "ENRICHED: %s = %r (source=%s)",
                target_field, found_value, found_source,
            )
        else:
            enrichment_log.append({
                "field_key": target_field,
                "status": "not_found",
                "source": "none",
            })
            logger.info(
                "ENRICHMENT_MISS: %s — not found in any source", target_field
            )

    return payload, enrichment_log


# ────────────────────────── extractors ──────────────────────────


def extract_duration_from_text(text: str) -> str | None:
    """Extract a course duration from text using regex.

    Returns a normalised string like ``"2 Years"`` or ``"24 Months"``,
    or ``None`` if no valid duration is found.  Filters out unreasonable
    values (e.g. "25 Years of Excellence").
    """
    for pattern in _DURATION_PATTERNS:
        match = pattern.search(text)
        if match:
            duration = _normalise_duration(match.group(0))
            # Validate: must be a reasonable course duration
            m = re.search(r"(\d+)", duration)
            if m:
                num = int(m.group(1))
                if "Year" in duration and 1 <= num <= 6:
                    return duration
                if "Month" in duration and 1 <= num <= 72:
                    return duration
    return None


def extract_fee_from_text(text: str) -> str | None:
    """Extract a total fee amount from text using regex.

    Prefers explicit labels (``"Total Fee: ₹1,00,000"``).
    Falls back to the largest currency amount ≥ 10,000.
    Excludes EMI amounts.

    Returns a string like ``"₹1,00,000"`` or ``None``.
    """
    # Strategy 1: explicit fee labels
    for pattern in _FEE_SPECIFIC_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_number = match.group(1)
            numeric = _parse_indian_number(raw_number)
            if numeric is not None and numeric >= 5000:
                return f"₹{raw_number}"

    # Strategy 2: largest currency amount (excluding EMI context)
    largest_raw = _find_largest_currency(text, min_amount=10000)
    if largest_raw:
        return f"₹{largest_raw}"

    return None


def extract_emi_from_text(text: str) -> str | None:
    """Extract an EMI amount from text using regex.

    Only matches amounts with explicit EMI or per-month context.

    Returns a string like ``"₹5,725/month"`` or ``None``.
    """
    for pattern in _EMI_PATTERNS:
        match = pattern.search(text)
        if match:
            raw_number = match.group(1)
            numeric = _parse_indian_number(raw_number)
            if numeric is not None and 500 <= numeric <= 100000:
                return f"₹{raw_number}/month"
    return None


# Extractor dispatch table
_EXTRACTORS: dict[str, Any] = {
    "duration": extract_duration_from_text,
    "fee": extract_fee_from_text,
    "emi": extract_emi_from_text,
}


# ────────────────────────── helpers ──────────────────────────


def _normalise_duration(raw: str) -> str:
    """Clean up a raw duration match into ``"N Years"`` or ``"N Months"``."""
    # Strip leading label ("duration:", "course duration –")
    raw = re.sub(
        r"^(?:course\s+)?duration\s*[:\-–]\s*",
        "",
        raw,
        flags=re.IGNORECASE,
    ).strip()

    m = re.search(
        r"(\d+)\s*[-–]?\s*(year|years|yr|yrs|month|months|mo|mos)\b",
        raw,
        re.IGNORECASE,
    )
    if not m:
        return raw

    num = int(m.group(1))
    unit_raw = m.group(2).lower()
    if unit_raw.startswith("y"):
        unit = "Year" if num == 1 else "Years"
    else:
        unit = "Month" if num == 1 else "Months"
    return f"{num} {unit}"


def _parse_indian_number(raw: str) -> int | None:
    """Parse an Indian-format number string to int.

    Handles: ``"1,00,000"`` → ``100000``, ``"100,000"`` → ``100000``.
    """
    try:
        return int(raw.replace(",", ""))
    except (ValueError, TypeError):
        return None


def _find_largest_currency(text: str, min_amount: int = 10000) -> str | None:
    """Find the largest currency amount in *text*, excluding EMI context."""
    largest_num = 0
    largest_raw: str | None = None

    for m in _GENERIC_CURRENCY_RE.finditer(text):
        raw = m.group(1)
        num = _parse_indian_number(raw)
        if num is None or num < min_amount:
            continue

        # Exclude if surrounded by EMI / per-month context
        start = max(0, m.start() - 40)
        before = text[start:m.start()].lower()
        after_end = min(len(text), m.end() + 30)
        after = text[m.end():after_end].lower()
        if "emi" in before or "/month" in after or "per month" in after:
            continue

        if num > largest_num:
            largest_num = num
            largest_raw = raw

    return largest_raw


def _flatten_value(value: Any) -> str:
    """Flatten a payload value (str / list / dict) into searchable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return _strip_html(value)
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.extend(_strip_html(str(v)) for v in item.values())
            elif isinstance(item, str):
                parts.append(_strip_html(item))
            else:
                parts.append(str(item))
        return " ".join(parts)
    if isinstance(value, dict):
        return " ".join(_strip_html(str(v)) for v in value.values())
    return str(value)


def _flatten_section_content(content: Any) -> str:
    """Flatten section-map content into searchable plain text."""
    if isinstance(content, str):
        return _strip_html(content)
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if "question" in item:
                    parts.append(
                        f"{item.get('question', '')} {item.get('answer', '')}"
                    )
                elif "headers" in item:
                    parts.append(" ".join(item.get("headers", [])))
                    for row in item.get("rows", []):
                        parts.append(" ".join(row))
                elif "text" in item:
                    parts.append(_strip_html(item["text"]))
                else:
                    parts.extend(str(v) for v in item.values())
            elif isinstance(item, str):
                parts.append(_strip_html(item))
            else:
                parts.append(str(item))
        return " ".join(parts)
    if isinstance(content, dict):
        sub_parts: list[str] = []
        if "paragraphs" in content:
            sub_parts.append(_strip_html(str(content["paragraphs"])))
        if "tables" in content:
            sub_parts.append(_flatten_section_content(content["tables"]))
        return " ".join(sub_parts) if sub_parts else str(content)
    return str(content)
