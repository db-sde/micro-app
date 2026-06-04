"""
AI content extractor — uses Anthropic Claude claude-haiku-4-5-20251001 to:
  1. Extract and format section content for specific ACF field types
  2. Confirm ambiguous heading → field mappings (medium confidence range)
  3. Resolve highly ambiguous mappings (low confidence range) with candidate list

Every function returns a plain Python dict that can be serialised to JSON.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from schemas import FIELDS_BY_TYPE, FIELD_TYPES_BY_TYPE

load_dotenv()
logger = logging.getLogger(__name__)

# ────────────────────────── client ──────────────────────────

_anthropic: Anthropic | None = None


def _get_client() -> Anthropic:
    global _anthropic
    if _anthropic is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key or api_key.startswith("your_"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Please add it to .env."
            )
        _anthropic = Anthropic(api_key=api_key)
    return _anthropic


_MODEL = "claude-haiku-4-5-20251001"

# ────────────────────────── system prompt ──────────────────────────

SYSTEM_PROMPT = """\
You are a content extraction specialist for an education listing platform.
You receive raw content from Word document sections and format it for WordPress ACF fields.

FIELD TYPE RULES — follow exactly:
- text:       Plain string. No HTML. No markdown. Max 1–2 sentences for heading fields.
- wysiwyg:    Clean HTML using ONLY <p> <ul> <ol> <li> <strong> <em> <h3> <h4> tags. No div, span, br.
- stat:       Short badge value like "85,000+" or "24 Months" or "A+". Max 10 characters total.
- table:      Valid JSON array of objects. ALWAYS an array. NEVER a flat string.
- bullet:     JSON array of strings. Each string is one bullet item.
- faq:        JSON array of {"question": "...", "answer": "..."} objects.

STAT EXTRACTION: For stat fields, extract just the number+unit.
  Examples: "85,000+" not "The university has 85,000+ students"
            "A+" not "NAAC Grade A+"
            "24 Months" not "The program duration is 24 months"

FAQ DETECTION: If content has alternating bullet points (odd=question, even=answer),
treat them as FAQ pairs. Extract as [{"question": "...", "answer": "..."}].

MISSING CONTENT: If the section content is empty or clearly unrelated to the field,
return {"value": null}.

RETURN FORMAT — always return valid JSON, nothing else:
{"value": <extracted value>}

No preamble. No explanation. No markdown fences. Raw JSON only.
"""

# ────────────────────────── stat question map ──────────────────────────

STAT_QUESTIONS: dict[str, str] = {
    "stat_students": "How many total students are enrolled?",
    "stat_alumni": "How many alumni does the university have?",
    "stat_hiring_partners": "How many hiring/placement partners?",
    "stat_years": "How many years of excellence/experience?",
    "stat_programs": "How many programs/courses are offered?",
    "duration": "What is the course duration?",
    "total_fee": "What is the total course fee?",
    "emi_amount": "What is the monthly EMI amount?",
    "spec_total_fee": "What is the total specialization fee?",
    "spec_emi": "What is the monthly EMI for this specialization?",
}

# ────────────────────────── field extraction hints ──────────────────────────

# Field-specific extraction instructions prepended to the content.
# The LLM sees these regardless of which extraction function is called.
FIELD_EXTRACTION_HINTS: dict[str, str] = {
    "placement_partners": (
        "IMPORTANT: Extract ONLY company/organisation names. "
        "Look for proper nouns — names like Amazon, TCS, Infosys, DishTV, CMC Limited. "
        "IGNORE support services text like 'resume building', 'interview prep', 'career guidance'. "
        "Return a JSON array of strings: each string is one company name."
    ),
    "specializations": (
        "IMPORTANT: Extract the list of specialization/track names. "
        "These are proper noun phrases like 'Marketing', 'Finance', 'Human Resource Management', "
        "'Healthcare and Hospital Administration'. "
        "Return a JSON array of strings: each string is one specialization name."
    ),
    "course_facts": (
        "Extract key facts or highlights about the course. "
        "Each fact should be a complete, meaningful sentence or bullet point. "
        "Return a JSON array of strings."
    ),
    "faqs": (
        "Extract question-answer pairs from the content. "
        "Content may have alternating bullets (odd = question, even = answer), "
        "or explicit Q:/A: labels, or paragraph-style Q&A. "
        "Return a JSON array of {\"question\": \"...\", \"answer\": \"...\"} objects."
    ),
    "reviews": (
        "Extract individual student reviews or testimonials as separate items. "
        "Each paragraph is typically one review. "
        "Return a JSON array of strings, each string is one review."
    ),
    "job_roles": (
        "Extract job role names and associated salary information. "
        "Each row should be one job role with its average salary if available. "
        "Return a JSON array of objects."
    ),
    "spec_about": (
        "Extract a comprehensive overview/description of the specialization. "
        "Format as clean HTML paragraphs."
    ),
}

# ────────────────────────── helpers ──────────────────────────


def _call_claude(system: str, user_prompt: str) -> str:
    """Send a single message to Claude and return the text response."""
    client = _get_client()
    try:
        message = client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return message.content[0].text.strip()
    except Exception as exc:
        logger.error("Claude API call failed: %s", exc)
        raise RuntimeError(f"Anthropic API call failed: {exc}") from exc


def _parse_json_response(raw: str) -> dict[str, Any]:
    """Try to parse JSON from Claude's response.

    Falls back to regex extraction if the response is wrapped in markdown
    code fences or contains preamble text.
    """
    # 1. Direct parse
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Find first { … } or [ … ]
    brace = raw.find("{")
    bracket = raw.find("[")
    start = -1
    if brace >= 0 and (bracket < 0 or brace < bracket):
        start = brace
    elif bracket >= 0:
        start = bracket

    if start >= 0:
        candidate = raw[start:]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 4. Give up
    logger.warning("Could not parse JSON from Claude response: %.200s", raw)
    return {"value": None, "parse_error": True}


def _content_to_text(content: Any) -> str:
    """Flatten arbitrary section content into a text block for the prompt."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("question"):
                    parts.append(f"Q: {item['question']}")
                    parts.append(f"A: {item.get('answer', '')}")
                elif item.get("headers"):
                    headers = item["headers"]
                    parts.append(" | ".join(headers))
                    for row in item.get("rows", []):
                        parts.append(" | ".join(row))
                elif item.get("type") == "paragraph":
                    parts.append(item.get("text", ""))
                elif item.get("type") == "table":
                    for row in item.get("rows", []):
                        parts.append(" | ".join(row))
                else:
                    parts.append(str(item))
            elif isinstance(item, str):
                parts.append(item)
            else:
                parts.append(str(item))
        return "\n".join(parts)
    if isinstance(content, dict):
        sub_parts: list[str] = []
        if "paragraphs" in content:
            sub_parts.append(str(content["paragraphs"]))
        if "tables" in content:
            sub_parts.append(_content_to_text(content["tables"]))
        return "\n".join(sub_parts) if sub_parts else str(content)
    return str(content)


# ────────────────────────── extraction by field type ──────────────────────────


def extract_field(
    field_key: str,
    field_type: str,
    content: Any,
    section_map_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract and format content for a single ACF field.

    Parameters
    ----------
    field_key : str
        The target ACF field key (e.g. ``"about_content"``).
    field_type : str
        One of ``"text"``, ``"wysiwyg"``, ``"stat"``, ``"table"``,
        ``"bullet"``, ``"faq"``.
    content : Any
        The raw section content from the docx parser.
    section_map_entry : dict | None
        The full section map entry (with ``type`` and ``content`` keys).
        Used for richer context if available.

    Returns
    -------
    dict
        ``{"value": <extracted>, ...}``
    """
    text_block = _content_to_text(content)

    if not text_block.strip():
        return {
            "value": None,
            "reason": "empty_content",
            "flag": "Section heading found but content is empty or whitespace-only",
        }

    # Prepend field-specific extraction hint if available
    hint = FIELD_EXTRACTION_HINTS.get(field_key, "")
    if hint:
        text_block = hint + "\n\n" + text_block

    if field_type == "text":
        return _extract_text(field_key, text_block)
    elif field_type == "wysiwyg":
        return _extract_wysiwyg(field_key, text_block)
    elif field_type == "stat":
        return _extract_stat(field_key, text_block)
    elif field_type == "table":
        return _extract_table(field_key, text_block)
    elif field_type == "bullet":
        return _extract_bullet(field_key, text_block)
    elif field_type == "faq":
        return _extract_faq(field_key, text_block)
    else:
        # Unknown type — fallback to wysiwyg
        return _extract_wysiwyg(field_key, text_block)


def _extract_text(field_key: str, text_block: str) -> dict[str, Any]:
    """Extract a short plain-text value (e.g. university name)."""
    prompt = (
        f"Extract the value for the field '{field_key}' from the following "
        f"document section. Return a short plain-text value.\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY: {{"value": "extracted text here"}}'
    )
    raw = _call_claude(SYSTEM_PROMPT, prompt)
    return _parse_json_response(raw)


def _extract_wysiwyg(field_key: str, text_block: str) -> dict[str, Any]:
    """Convert section to clean HTML for a WYSIWYG ACF field."""
    prompt = (
        f"Convert the following content to clean HTML for the WordPress ACF "
        f"field '{field_key}'. Use only <p>, <ul>, <li>, <ol>, <strong>, "
        f"<em>, <h3>, <h4> tags. Preserve ALL content — do not summarise. "
        f"Do not add information that isn't present.\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY: {{"value": "<p>…</p>"}}'
    )
    raw = _call_claude(SYSTEM_PROMPT, prompt)
    return _parse_json_response(raw)


def _extract_stat(field_key: str, text_block: str) -> dict[str, Any]:
    """Extract a single statistic value."""
    question = STAT_QUESTIONS.get(
        field_key, f"What is the value for '{field_key}'?"
    )
    prompt = (
        f"From the following content, answer this question: {question}\n\n"
        f"Return the value with its suffix only, e.g. 89K+ or INR 1,99,000 "
        f"or 30+ or 2 Years. If the answer is not found, return exactly: "
        f"Not found.\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY: {{"value": "…"}}'
    )
    raw = _call_claude(SYSTEM_PROMPT, prompt)
    result = _parse_json_response(raw)

    # Treat "Not found" as None
    if isinstance(result.get("value"), str) and result["value"].strip().lower() in (
        "not found",
        "n/a",
        "na",
        "none",
    ):
        result["value"] = None

    return result


def _extract_table(field_key: str, text_block: str) -> dict[str, Any]:
    """Extract tabular data as a JSON array of row objects."""
    prompt = (
        f"Convert the following table/tabular data to a JSON array for the "
        f"ACF field '{field_key}'. Each row should be one JSON object. "
        f"Normalise all keys to lowercase with underscores (e.g. "
        f"'Course Name' → 'course_name'). Preserve all rows and data.\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY: {{"value": [{{...}}, {{...}}]}}'
    )
    raw = _call_claude(SYSTEM_PROMPT, prompt)
    result = _parse_json_response(raw)

    # Validate that value is actually a list
    val = result.get("value")
    if val is not None and not isinstance(val, list):
        # Try to parse it if it's a string
        if isinstance(val, str):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    result["value"] = parsed
                else:
                    result["value"] = None
                    result["structure_error"] = True
            except json.JSONDecodeError:
                result["value"] = None
                result["structure_error"] = True

    return result


def _extract_bullet(field_key: str, text_block: str) -> dict[str, Any]:
    """Extract bullet-point content as a JSON array of strings."""
    prompt = (
        f"Convert the following bullet points / list items to a JSON array "
        f"of strings for the ACF field '{field_key}'. Preserve the complete "
        f"text of each item. Remove bullet markers (•, -, numbers).\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY: {{"value": ["item 1", "item 2", …]}}'
    )
    raw = _call_claude(SYSTEM_PROMPT, prompt)
    return _parse_json_response(raw)


def _extract_faq(field_key: str, text_block: str) -> dict[str, Any]:
    """Extract FAQ content as a JSON array of {question, answer} objects."""
    prompt = (
        f"Convert the following Q&A / FAQ content to a JSON array of objects "
        f"for the ACF field '{field_key}'. Each object must have 'question' "
        f"and 'answer' keys. Preserve full text.\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY: {{"value": [{{"question":"…","answer":"…"}}]}}'
    )
    raw = _call_claude(SYSTEM_PROMPT, prompt)
    return _parse_json_response(raw)


# ────────────────────────── mapping confirmation ──────────────────────────


def confirm_mapping(
    heading: str,
    content: Any,
    candidate_field: str,
    page_type: str,
) -> dict[str, Any]:
    """Ask Claude whether *heading* genuinely maps to *candidate_field*.

    Used for similarity scores in the THRESHOLD_VERIFY – THRESHOLD_AUTO range where the embedding
    match is probable but not certain.

    Returns ``{"confirmed": bool, "field_key": str, "reason": str}``.
    """
    fields_desc = FIELDS_BY_TYPE.get(page_type, {})
    field_desc = fields_desc.get(candidate_field, candidate_field)
    text_block = _content_to_text(content)
    preview = text_block[:500]

    prompt = (
        f"I have a document section with heading: \"{heading}\"\n"
        f"Content preview: \"{preview}\"\n\n"
        f"I believe this maps to the ACF field '{candidate_field}' "
        f"(description: {field_desc}).\n\n"
        f"Does this heading+content genuinely correspond to this field? "
        f"Consider both the heading text and the content.\n\n"
        f'Return ONLY: {{"confirmed": true/false, "field_key": "{candidate_field}", '
        f'"reason": "brief explanation"}}'
    )

    raw = _call_claude(SYSTEM_PROMPT, prompt)
    result = _parse_json_response(raw)

    # Ensure required keys exist
    if "confirmed" not in result:
        result["confirmed"] = False
    if "field_key" not in result:
        result["field_key"] = candidate_field

    return result


def resolve_ambiguous(
    heading: str,
    content: Any,
    candidates: list[dict[str, Any]],
    page_type: str,
) -> dict[str, Any]:
    """Ask Claude to pick the best field from multiple candidates.

    Used for similarity scores in the THRESHOLD_FALLBACK – THRESHOLD_VERIFY range where the embedding
    is unsure which field is correct.

    Parameters
    ----------
    candidates : list[dict]
        Top-3 matches from the embedder, each with ``field_key`` and ``score``.

    Returns ``{"field_key": str, "confidence": float, "reason": str}``.
    """
    fields_desc = FIELDS_BY_TYPE.get(page_type, {})
    text_block = _content_to_text(content)
    preview = text_block[:500]

    options = "\n".join(
        f"  {i+1}. {c['field_key']} — {fields_desc.get(c['field_key'], c['field_key'])} (embedding score: {c['score']})"
        for i, c in enumerate(candidates)
    )

    prompt = (
        f"I have a document section with heading: \"{heading}\"\n"
        f"Content preview: \"{preview}\"\n\n"
        f"Which of these ACF fields does this section best match?\n{options}\n"
        f"  4. NONE — this section doesn't match any of these fields\n\n"
        f"Consider both the heading and content semantics.\n\n"
        f'Return ONLY: {{"field_key": "chosen_key_or_none", '
        f'"confidence": 0.0_to_1.0, "reason": "brief explanation"}}'
    )

    raw = _call_claude(SYSTEM_PROMPT, prompt)
    result = _parse_json_response(raw)

    # Normalise
    if "field_key" not in result:
        result["field_key"] = "none"
    if "confidence" not in result:
        result["confidence"] = 0.0
    if result["field_key"].lower() == "none":
        result["field_key"] = None

    return result
