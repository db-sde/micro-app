"""
Page-type detector — Uses Anthropic Claude to classify the document based on its
initial headings and content.

Returns the most likely page type: "university", "course", or "specialization".
"""

from __future__ import annotations

import logging
from typing import Any

from pipeline.extractor import call_claude, parse_json_response, content_to_text

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an expert document classifier for an education platform.
Your task is to determine the page type of a document based on its initial sections.

The page type MUST be exactly one of:
- "university": A general page about a university, its campus, overall placement, etc.
- "course": A page about a specific degree program (e.g., MBA, B.Tech, MCA).
- "specialization": A page about a specific track within a degree (e.g., MBA in Marketing, B.Tech in Computer Science).

Rules:
1. Pay close attention to the first heading/title. If it mentions a specific degree (MBA, MCA, BA) or specialization, it is likely a "course" or "specialization".
2. If the document has "semesters", "syllabus", or specific "eligibility" for a degree, it is NOT a university.
3. Return ONLY a valid JSON object with a single key "page_type" and the string value.

Example output:
{"page_type": "course"}
"""

def detect_page_type(section_map: dict[str, dict[str, Any]]) -> str:
    """Use Claude to determine the page type based on the first few sections.

    Parameters
    ----------
    section_map : dict
        Keys are heading strings from the parsed document.

    Returns
    -------
    str
        One of ``"university"``, ``"course"``, ``"specialization"``.
        Falls back to ``"university"`` on failure.
    """
    # 1. Build a summary of the first few sections
    summary_parts = []
    
    # We only need the first ~5 meaningful headings to make a decision
    count = 0
    for heading, data in section_map.items():
        if heading.startswith("__"):
            continue
        
        content = data.get("content", "")
        text = content_to_text(content)
        # truncate text to avoid sending too much
        if len(text) > 400:
            text = text[:400] + "..."
            
        summary_parts.append(f"Heading: {heading}\nContent: {text}")
        count += 1
        if count >= 5:
            break
            
    if not summary_parts:
        return "university"
        
    document_summary = "\n\n".join(summary_parts)
    
    prompt = (
        f"Analyze the following document summary and determine the page type.\n\n"
        f"Document Summary:\n{document_summary}\n\n"
        f'Return ONLY: {{"page_type": "university" | "course" | "specialization"}}'
    )
    
    try:
        raw = call_claude(SYSTEM_PROMPT, prompt)
        result = parse_json_response(raw)
        pt = result.get("page_type")
        
        if pt in ("university", "course", "specialization"):
            return pt
            
        logger.warning("Claude returned invalid page type: %s, falling back to university", pt)
    except Exception as exc:
        logger.error("LLM page detection failed: %s", exc)
        
    return "university"
