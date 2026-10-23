"""v2's extraction call: the whole document in, every field out.

The system prompt holds the rules; the JSON Schema (pipeline/v2/schema.py)
holds every field and, as each field's description, what that field is on
the published page. The document goes in the user turn with its page type
and title.

A document too large for one request (MAX_DOC_TOKENS, far above any
content doc seen so far) is split at top-level headings; every part gets
the title and the full field list, and the answers are merged.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.v2 import claude
from pipeline.v2.schema import field_groups, output_schema

logger = logging.getLogger("degreebaba.v2.extract")

PROMPT_VERSION = "v2.5"  # v2.5: never invent step titles; look for short facts everywhere. v2.4: flat syllabus rows; field groups
# v2.2: hero text from the document; headings of tagged sections. v2.3: same rule in each heading's description.
MAX_DOC_TOKENS = int(os.getenv("V2_MAX_DOC_TOKENS", "300000"))
_CHARS_PER_TOKEN = 3.5

SYSTEM_PROMPT = """\
You fill the fields of one page on DegreeBaba, an Indian online-education listing site, from the content document the team wrote for that page. The document is a Word file converted to Markdown. The page type (university, course or specialization) is given with the document. The JSON schema lists every field of that page type; each field's description says what the field is on the published page and how to fill it. Read the whole document before filling anything: a section's content can depend on another section.

Rules:
1. Copy, don't create. Every value comes from the document. You may reshape text into the format a field asks for (HTML, rows), but never add facts, numbers, names or claims the document doesn't contain. When the document has nothing for a field, return "" (or [] for lists).
2. No placeholders. Never write "N/A", "NA", "nil", "-", "not available", "TBD" or similar; use "" instead.
3. Headings are headings. A *_heading field is that section's own heading as written, without any [tag] prefix: short, never a sentence, a fee or a table row.
4. The page's own name (university_name, program_name or spec_name) comes from the document title, not from body text or tables.
5. Writers mark some headings with [field_name] or [field_a, field_b] tags. They say which fields the section's content belongs to; follow them unless the content plainly says otherwise. A tag doesn't need to name the heading field: a section's own heading still fills the matching *_heading field (a section tagged [exam_content] titled "Examination Process of X" gives exam_heading "Examination Process of X"). Lines like "Linked_university - X" or "Linked_course - X" are relationship hints, not page content, and notes to editors (change logs, keyword-density tables) are not page content either.
6. Lists are complete. Repeater fields hold every row or item the document gives, in document order. Never summarise, sample or truncate a list or table.
7. Admission steps are one ordered list. Bold "Step N. Title:" lines are steps, not sections; keep each step's title in <strong> with its description. Text after the last step ("Additional information", "Important instructions") is the admission note, not a step.
8. HTML fields use only <p> <ul> <ol> <li> <strong> <em> <h3> <h4>, keep all of their section's content, and never start with the section's own heading.
9. Provenance: for every field you fill, add one entry with the heading of the document section it came from, as written (without # marks), and your confidence: "high" when the document states it plainly, "medium" when you had to choose between sections or interpret, "low" when unsure.
10. Facts can be anywhere. Short facts (NAAC grade, NIRF rank, UGC status, mode, duration, validity, eligibility) are often only in a Quick facts block, an accreditation bullet or an FAQ answer; look through the whole document, FAQs included, before leaving one empty.
11. Notes: briefly note content that fits no field, and anything contradictory (for example two different totals for the same fee).
"""


@dataclass
class Extraction:
    values: dict[str, Any]
    provenance: list[dict[str, str]]
    notes: list[str]
    calls: list[claude.CallResult] = field(default_factory=list)

    @property
    def cost_usd(self) -> float:
        return round(sum(c.cost_usd for c in self.calls), 4)

    @property
    def usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for c in self.calls:
            for k, v in c.usage.items():
                total[k] = total.get(k, 0) + v
        return total


def user_message(markdown: str, page_type: str, title: str, part: str = "") -> str:
    part_line = f"\nThis is {part} of the document; fill only what this part contains.\n" if part else ""
    return (
        f"<document>\n{markdown}\n</document>\n\n"
        f"Page type: {page_type}\n"
        f"Document title: {title}\n"
        f"{part_line}\n"
        f"Fill the fields of this {page_type} page from the document."
    )


def estimate_tokens(text: str) -> int:
    return int(len(text) / _CHARS_PER_TOKEN)


def split_markdown(markdown: str, max_tokens: int) -> list[str]:
    """Split at the highest heading level used, keeping sections whole."""
    levels = [len(m.group(1)) for m in re.finditer(r"^(#{1,6}) ", markdown, re.M)]
    if not levels:
        return [markdown]
    top = min(levels)
    sections = [s for s in re.split(rf"(?m)^(?=#{{{top}}} )", markdown) if s]
    if len(sections) > 1 and not sections[0].startswith("#"):
        sections[1] = sections[0] + sections[1]  # the title/preamble travels with the first section
        sections = sections[1:]
    parts, current = [], ""
    for section in sections:
        if current and estimate_tokens(current + section) > max_tokens:
            parts.append(current)
            current = ""
        current += section
    if current:
        parts.append(current)
    return parts


def _filled(value: Any) -> bool:
    return bool(value.strip()) if isinstance(value, str) else bool(value)


def merge(answers: list[dict[str, Any]]) -> dict[str, Any]:
    """Parts in document order: first filled scalar wins, lists are joined."""
    values: dict[str, Any] = {}
    provenance: list[dict[str, str]] = []
    notes: list[str] = []
    for answer in answers:
        source = {p.get("field"): p for p in answer.get("provenance") or []}
        for key, value in (answer.get("values") or {}).items():
            if isinstance(value, list):
                if value:
                    existing = values.setdefault(key, [])
                    existing.extend(r for r in value if r not in existing)
                    if key in source and not any(p["field"] == key for p in provenance):
                        provenance.append(source[key])
                else:
                    values.setdefault(key, [])
            elif _filled(value) and not _filled(values.get(key)):
                values[key] = value
                if key in source:
                    provenance = [p for p in provenance if p["field"] != key] + [source[key]]
            else:
                values.setdefault(key, value)
        notes += answer.get("notes") or []
    return {"values": values, "provenance": provenance, "notes": notes}


# Page types whose one-request schema is too large to compile: their fields go
# in two requests. Course and specialization were rejected by the API
# ("compiled grammar is too large"); others are added here when that happens.
_GROUPED: set[str] = {"course", "specialization"}
GROUP_NOTE = "This request covers only the fields in the schema; another request fills the rest. "


def grammar_too_large(exc: Exception) -> bool:
    """The 400 the API returns when a JSON schema compiles to too large a grammar."""
    msg = str(exc).lower()
    return getattr(exc, "status_code", None) == 400 and ("grammar" in msg or "too complex" in msg)


def _calls_for_part(part: str, page_type: str, title: str, label: str, model, effort, client) -> list[claude.CallResult]:
    def run(groups):
        results = []
        for keys in groups:
            user = user_message(part, page_type, title, label)
            if keys is not None:
                user = user.replace("\nFill the fields", f"\n{GROUP_NOTE}Fill the fields")
            results.append(claude.call_json(system=SYSTEM_PROMPT, user=user, schema=output_schema(page_type, keys),
                                            model=model, effort=effort, client=client))
        return results

    if page_type in _GROUPED:
        return run(field_groups(page_type))
    try:
        return run([None])
    except Exception as exc:
        if not grammar_too_large(exc):
            raise
        logger.warning("SCHEMA_TOO_LARGE: %s; extracting in %d field groups", page_type, len(field_groups(page_type)))
        _GROUPED.add(page_type)
        return run(field_groups(page_type))


def extract(markdown: str, page_type: str, title: str, model: str | None = None,
            effort: str | None = None, client=None) -> Extraction:
    effort = effort or os.getenv("V2_EFFORT", "high")
    if estimate_tokens(markdown) <= MAX_DOC_TOKENS:
        parts = [markdown]
    else:
        parts = split_markdown(markdown, MAX_DOC_TOKENS)
    calls: list[claude.CallResult] = []
    for i, part in enumerate(parts, 1):
        label = f"part {i} of {len(parts)}" if len(parts) > 1 else ""
        calls += _calls_for_part(part, page_type, title, label, model, effort, client)
    answers = [c.data for c in calls]
    data = answers[0] if len(answers) == 1 else merge(answers)
    return Extraction(values=data.get("values") or {}, provenance=data.get("provenance") or [],
                      notes=data.get("notes") or [], calls=calls)
