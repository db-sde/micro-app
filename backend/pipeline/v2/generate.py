"""SEO title, meta description, hero text and programs intro, written after
extraction from the final values, so they can't repeat a wrong name.

Only empty fields are filled.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pipeline.v2 import claude
from pipeline.v2.field_guide import PAGE_NAME_FIELD
from pipeline.v2.schema import GENERATED_FIELDS, GENERATED_IF_MISSING

RULES = {
    "seo_title": "50-60 characters. Include the page name exactly as given{uni}.",
    "meta_description": "140-160 characters: a compelling search snippet for this page.",
    "hero_description": "2-3 sentences, at most 300 characters, plain text: the banner text under the page name.",
    "specialization_hero_description": "2-3 sentences, at most 300 characters, plain text: the banner text under the specialization name.",
    "programs_intro": "One short line shown above the programs table.",
    "certificate_description": "1-2 sentences, plain text, about the degree/certificate this specialization leads to, as issued by the university.",
}

SYSTEM_PROMPT = """\
You write short page texts for DegreeBaba, an Indian online-education listing site, from facts already extracted from the page's content document. Use only the facts given: no other numbers, rankings, fees, placements or claims. Use the page name and university name exactly as given. Plain text, no markdown, no quotation marks around the whole text.
"""

# Facts that are useful for these texts, by field.
_FACT_FIELDS = (
    "university_name", "university_full_name", "program_name", "spec_name", "duration", "mode", "mode_of_learning",
    "naac_grade", "nirf_rank", "ugc_status", "ugc_approved", "established_year", "total_fee", "starting_fee",
    "emi_amount", "num_programs", "num_specializations", "validity", "program_validity", "eligibility_summary",
)
_LIST_FIELDS = {
    "specialization": "specialization_name", "highlights": "highlight_title", "job_profiles": "job_title",
    "programs_table": "program_name", "accreditations": "body_name", "course_accreditations": "course_body_name",
    "other_specs": "other_spec_name",
}


def _plain(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + " …"


def facts(payload: dict[str, Any], page_type: str) -> dict[str, Any]:
    out: dict[str, Any] = {"page_type": page_type, "page_name": payload.get(PAGE_NAME_FIELD[page_type])}
    for key in _FACT_FIELDS:
        if payload.get(key):
            out[key] = payload[key]
    for key, sub in _LIST_FIELDS.items():
        rows = payload.get(key)
        if isinstance(rows, list) and rows:
            out[key] = [r.get(sub) for r in rows if isinstance(r, dict) and r.get(sub)][:12]
    if payload.get("about_content"):
        out["about"] = _plain(payload["about_content"], 1500)
    return out


def targets(payload: dict[str, Any], page_type: str) -> list[str]:
    wanted = sorted(GENERATED_FIELDS.get(page_type, set()) | GENERATED_IF_MISSING.get(page_type, set()))
    if page_type == "specialization":
        wanted.append("certificate_description")
    return [k for k in wanted if not payload.get(k)]


def generate(payload: dict[str, Any], page_type: str, model: str | None = None, client=None):
    """-> (values for the empty generated fields, CallResult | None)."""
    keys = targets(payload, page_type)
    if not keys or not payload.get(PAGE_NAME_FIELD[page_type]):
        return {}, None
    uni = " and the university name" if page_type != "university" else ""
    schema = {
        "type": "object",
        "properties": {k: {"type": "string", "description": RULES[k].format(uni=uni)} for k in keys},
        "required": keys,
        "additionalProperties": False,
    }
    user = (f"Facts for this {page_type} page:\n{json.dumps(facts(payload, page_type), ensure_ascii=False, indent=1)}\n\n"
            f"Write: {', '.join(keys)}.")
    result = claude.call_json(system=SYSTEM_PROMPT, user=user, schema=schema, model=model,
                              effort="medium", max_tokens=16000, client=client)
    values = {k: str(result.data.get(k) or "").strip() for k in keys}
    return {k: v for k, v in values.items() if v}, result
