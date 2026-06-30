import logging
from anthropic import Anthropic
import os

logger = logging.getLogger("degreebaba.blog_pipeline")

_anthropic = None

def _get_client() -> Anthropic:
    global _anthropic
    if _anthropic is None:
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set.")
        _anthropic = Anthropic(api_key=api_key)
    return _anthropic

_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
You are an expert content writer for an education platform.
Your task is to read the raw text of a Blog or Category page and generate an engaging "Complete Page Summary".
This summary will be placed at the top of the page.

RULES:
- The summary MUST be highly appealing and optimized for short attention spans.
- The output MUST consist of exactly 4-5 key bullet points summarizing the core essence of the page.
- CRITICAL: Keep each bullet point extremely brief and punchy. Maximum 1-2 short sentences (or phrases) per point. Do not write huge, wordy paragraphs.
- Return the output strictly as a clean HTML unordered list (<ul>).
- Each point should be enclosed in an <li> tag.
- You may use <strong> tags inside the <li> for emphasis if helpful.
- DO NOT return any markdown formatting (like ```html). Return ONLY the raw HTML string starting with <ul> and ending with </ul>.
- DO NOT add introductory or concluding sentences.
"""

def generate_blog_summary(text: str, page_type: str = "blog") -> str:
    """Generate a 4-5 point bulleted summary of the provided text using Claude."""
    logger.info("Generating summary for %s (len: %d chars)", page_type, len(text))
    client = _get_client()
    
    user_prompt = f"Please read the following {page_type} content and generate the 4-5 point HTML bulleted summary:\n\n<content>\n{text}\n</content>"
    
    try:
        response = client.messages.create(
            model=_MODEL,
            max_tokens=800,
            temperature=0.4,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        # Type narrowing for Anthropic's response
        raw = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw += block.text
                
        # Clean up in case Claude still outputs markdown
        raw = raw.strip()
        if raw.startswith("```html"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
            
        import json
        payload = {
            "complete_page_summary": raw.strip()
        }
        return json.dumps(payload, indent=2)
    except Exception as exc:
        logger.error("Failed to generate blog summary: %s", exc)
        raise
