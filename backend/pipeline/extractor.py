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

from acf.fields import ACF_FIELDS, get_field_type

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

CRITICAL: You must properly escape all double quotes (\\") inside string values to ensure the output is valid JSON.
No preamble. No explanation. No markdown fences. Raw JSON only.

REPEATER STRUCTURES — For JSON array fields, use exactly these sub-field keys:
facts:            [{"fact_title": "...", "fact_description": "..."}]
accreditations:   [{"body_name": "NAAC", "body_descriptor": "A+ Grade", "body_detail": "Ranked top 10"}]
programs_table:   [{"program_name": "MBA", "program_fee": "₹45,000/-", "program_eligibility": "Bachelor's degree"}]
faculty_members:  [{"member_name": "Dr. Name", "member_program": "MBA", "member_designation": "Professor", "member_qualification": "Ph.D."}]
highlights:       [{"highlight_title": "Industry Mentors", "highlight_description": "Learn from CXOs"}]
fee_plans:        [{"plan_name": "Semester Plan", "plan_amount": "₹25,000", "plan_total": "Year I"}]
other_specs:      [{"other_spec_name": "Finance", "other_spec_fee": "₹1,75,000"}]
job_profiles:     [{"job_title": "Business Analyst", "avg_salary": "INR 5 LPA"}]
reviews:          [{"review_text": "Great experience...", "reviewer_label": "MBA Graduate, 2024"}]
faqs:             [{"question": "Is the degree valid?", "answer": "Yes, UGC entitled."}]
"""

# ────────────────────────── stat question map ──────────────────────────

STAT_QUESTIONS: dict[str, str] = {
    "established_year": "In what year was the university established?",
    "cdoe_year": "In what year was the CDOE/distance education department started?",
    "naac_grade": "What is the NAAC grade or score?",
    "starting_fee": "What is the starting fee or minimum fee?",
    "num_programs": "How many total programs or courses are offered?",
    "num_specializations": "How many specializations or tracks are available?",
    "duration": "What is the course duration?",
    "total_fee": "What is the total course fee?",
    "emi_amount": "What is the monthly EMI amount?",
}

# ────────────────────────── field extraction hints ──────────────────────────

# Field-specific extraction instructions prepended to the content.
# The LLM sees these regardless of which extraction function is called.
FIELD_EXTRACTION_HINTS: dict[str, str] = {
    "specializations": (
        "IMPORTANT: Extract the list of specialization/track names. "
        "These are proper noun phrases like 'Marketing', 'Finance', 'Human Resource Management', "
        "'Healthcare and Hospital Administration'. "
        "Return a JSON array of strings: each string is one specialization name."
    ),
    "faqs": (
        "Extract question-answer pairs from the content. "
        "Content may have alternating bullets (odd = question, even = answer), "
        "or explicit Q:/A: labels, or paragraph-style Q&A. "
        "Return a JSON array of {\"question\": \"...\", \"answer\": \"...\"} objects."
    ),
    "reviews": (
        "Extract individual student reviews or testimonials as separate items. "
        "Each paragraph or block is typically one review. "
        "Return a JSON array of objects with keys 'review_text' and 'reviewer_label'. "
        "'reviewer_label' should be the reviewer's role or identity if mentioned "
        "(e.g. 'MBA Student', 'Working Professional', 'Graduate 2024'). "
        "If no label is present for a review, use 'Student' as the default — never null."
    ),
    "admission_fee_note": (
        "IMPORTANT: Find the specific line, step, or sentence that mentions paying the application fee, "
        "registration fee, or program fee. Extract only that sentence or step as the admission fee note. "
        "Even if it is just a numbered step (e.g. 'Step 5. Pay the required fee...'), extract it."
    ),
    "faculty_intro": (
        "IMPORTANT: Extract the introductory text/paragraph that appears before the faculty table. "
        "Ignore the table completely. Return ONLY the introductory text."
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


def _ensure_dict(parsed: Any) -> dict[str, Any]:
    """Ensure the parsed JSON is always a dictionary to prevent AttributeErrors."""
    if isinstance(parsed, list):
        return {"value": parsed}
    if isinstance(parsed, dict):
        return parsed
    return {"value": parsed}

def _parse_json_response(raw: str) -> dict[str, Any]:
    """Try to parse JSON from Claude's response.

    Falls back to regex extraction if the response is wrapped in markdown
    code fences or contains preamble text.
    """
    # 1. Direct parse
    try:
        return _ensure_dict(json.loads(raw, strict=False))
    except json.JSONDecodeError:
        pass

    # 2. Extract from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
    if match:
        try:
            return _ensure_dict(json.loads(match.group(1), strict=False))
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
            return _ensure_dict(json.loads(candidate, strict=False))
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
        if "intro_text" in content:
            sub_parts.append(str(content["intro_text"]))
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
    heading: str | None = None,
) -> dict[str, Any]:
    """Extract and format content for a single ACF field."""
    text_block = _content_to_text(content)

    if heading:
        # Strip internal tags like [about_heading] before passing to Claude
        clean_heading = re.sub(r"^\[.*?\]\s*", "", heading).strip()
        text_block = f"Section Heading: {clean_heading}\n\n{text_block}"

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
    elif field_type == "textarea":
        return _extract_textarea(field_key, text_block)
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
    elif field_type == "json":
        return _extract_json_array(field_key, text_block)
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


def _extract_textarea(field_key: str, text_block: str) -> dict[str, Any]:
    """Extract a paragraph of text for a TEXTAREA field without forcing HTML tags."""
    prompt = (
        f"Extract the value for the field '{field_key}' from the following "
        f"document section. Return the plain text paragraph(s) only. "
        f"Do NOT include any tabular data. If you find the relevant paragraph, DO NOT return null.\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY: {{"value": "extracted text paragraph here"}}'
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


def _extract_json_array(field_key: str, text_block: str) -> dict[str, Any]:
    """Extract content as a JSON array of objects according to SYSTEM_PROMPT definitions."""
    prompt = (
        f"Convert the following content to a JSON array for the ACF field "
        f"'{field_key}'. Refer to the 'REPEATER STRUCTURES' in your system instructions "
        f"for the exact keys to use for this field. Preserve all relevant information.\n\n"
        f"Content:\n{text_block}\n\n"
        f'Return ONLY a valid JSON array: {{"value": [{{...}}, {{...}}]}}'
    )
    raw = _call_claude(SYSTEM_PROMPT, prompt)
    result = _parse_json_response(raw)

    val = result.get("value")
    
    # If Claude returned {"highlights": [...]} instead of {"value": [...]}
    if val is None and field_key in result:
        val = result[field_key]
        result["value"] = val
        
    # If Claude returned some other random key e.g. {"data": [...]}
    if val is None and len(result) == 1:
        first_val = next(iter(result.values()))
        if isinstance(first_val, list):
            val = first_val
            result["value"] = val

    if val is not None and not isinstance(val, list):
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


def generate_seo_and_intro(payload: dict[str, Any], page_type: str) -> dict[str, str]:
    """Generate SEO fields and intro subtitles using Claude based on the extracted payload."""
    if page_type == "university":
        target_fields = ["seo_title", "meta_description", "programs_intro"]
        rules = (
            "- seo_title: 50-60 characters, compelling.\n"
            "- meta_description: 140-160 characters, compelling search snippet.\n"
            "- programs_intro: One line subtitle to go above the programs table.\n"
        )
    elif page_type == "specialization":
        target_fields = ["seo_title", "meta_description"]
        rules = (
            "- seo_title: 50-60 characters, include the specialization and university name.\n"
            "- meta_description: 140-160 characters, compelling search snippet for this specialization.\n"
        )
    else:  # course
        target_fields = ["seo_title", "meta_description"]
        rules = (
            "- seo_title: 50-60 characters, include the program and university name.\n"
            "- meta_description: 140-160 characters, compelling search snippet.\n"
        )

    # We provide a summary of the payload to Claude to keep the prompt concise
    summary = {}
    for k, v in payload.items():
        if v and not isinstance(v, list) and k not in target_fields:
            # truncate long HTML contents for the prompt
            val_str = str(v)
            if len(val_str) > 500:
                val_str = val_str[:500] + "..."
            summary[k] = val_str

    prompt = (
        f"Based on the following extracted data for a {page_type} page, generate the following fields:\n"
        f"{', '.join(target_fields)}\n\n"
        f"Rules:\n"
        f"{rules}\n"
        f"Data:\n{json.dumps(summary, indent=2)}\n\n"
        f"Return ONLY a valid JSON object with keys: {', '.join(target_fields)}."
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
    fields_desc = {f["key"]: f["embed"] for f in ACF_FIELDS.get(page_type, [])}
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
    fields_desc = {f["key"]: f["embed"] for f in ACF_FIELDS.get(page_type, [])}
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
