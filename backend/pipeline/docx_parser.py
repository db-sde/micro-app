"""
DOCX parser — extracts a structured section map from a .docx byte stream.

The section map is a dict keyed by *stripped* heading text.  Each value is::

    {
        "original_heading": str,     # heading as it appeared in the document
        "type": str,                 # paragraph / bullet / table / faq / mixed
        "content": <formatted data>  # varies by type
    }

Heading detection:
  1. Paragraph has a style whose name contains "Heading"
  2. *All* runs are bold **and** the largest font-size ≥ 14 pt

Content type detection:
  - FAQ:   list of items where every odd-indexed (0-based) item ends with "?"
  - Table: content contains at least one table element
  - Bullet: ≥ 60 % of paragraphs start with bullet-like markers
  - Paragraph: everything else
"""

from __future__ import annotations

import io
import re
from typing import Any

from docx import Document
from docx.shared import Pt
import mammoth


# ────────────────────────── public API ──────────────────────────


def parse_docx(file_bytes: bytes) -> dict[str, dict[str, Any]]:
    """Return a section map extracted from the given *.docx* bytes."""

    doc = Document(io.BytesIO(file_bytes))

    # Pre-index paragraphs and tables by their underlying XML element id so
    # we can look them up in O(1) while walking the body in document order.
    _para_by_elem: dict[int, Any] = {id(p._element): p for p in doc.paragraphs}
    _table_by_elem: dict[int, Any] = {id(t._element): t for t in doc.tables}

    # ── walk the body in document order ──
    sections: dict[str, list[dict[str, Any]]] = {}
    current_heading: str = "Introduction"
    current_content: list[dict[str, Any]] = []

    for child in doc.element.body:
        eid = id(child)

        # ── paragraph ──
        if child.tag.endswith("}p"):
            para = _para_by_elem.get(eid)
            if para is None:
                continue

            text = para.text.strip()
            if not text:
                continue

            if _is_heading(para):
                # flush previous section
                if current_content:
                    sections[current_heading] = current_content
                current_heading = text
                current_content = []
            else:
                current_content.append({"type": "paragraph", "text": text})

        # ── table ──
        elif child.tag.endswith("}tbl"):
            table = _table_by_elem.get(eid)
            if table is None:
                continue
            rows: list[list[str]] = []
            for row in table.rows:
                rows.append([cell.text.strip() for cell in row.cells])
            if rows:
                current_content.append({"type": "table", "rows": rows})

    # flush last section
    if current_content:
        sections[current_heading] = current_content

    # ── build final section map with type detection ──
    section_map: dict[str, dict[str, Any]] = {}
    for heading, content in sections.items():
        stripped = _strip_prefix(heading)
        section_type, formatted = _detect_and_format(content)
        section_map[stripped] = {
            "original_heading": heading,
            "type": section_type,
            "content": formatted,
        }

    # Also convert the whole document to HTML via mammoth for fallback use
    try:
        mammoth_result = mammoth.convert_to_html(io.BytesIO(file_bytes))
        section_map["__full_html__"] = {
            "original_heading": "__full_html__",
            "type": "html",
            "content": mammoth_result.value,
        }
    except Exception:
        pass

    return section_map


# ────────────────────────── helpers ──────────────────────────

_BULLET_RE = re.compile(
    r"^(?:[•●○▪▸▹►–—-]\s*|\d+[.)]\s+|[a-zA-Z][.)]\s+|[\u2022\u2023\u25E6\u2043\u2219]\s*)"
)

_PREFIX_STRIP_RE = re.compile(
    r"^(?:Online\s+)?(?:Sharda|Amity|Manipal|Jain|LPU|Lovely\s+Professional|Chandigarh|"
    r"UPES|Amrita|Sikkim\s+Manipal|DY\s+Patil|Vignan|NMIMS|Uttaranchal|"
    r"Symbiosis|Presidency|Mysore|Suresh\s+Gyan\s+Vihar|Vivekananda|"
    r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:University|Institute|College)\s+"
    r"(?:Online\s+)?(?:MBA|MCA|BBA|BCA|B\.?Com|M\.?Com|BA|MA|B\.?Sc|M\.?Sc|"
    r"B\.?Tech|M\.?Tech|PhD|PGDM|Diploma|Certificate)?\s*",
    re.IGNORECASE,
)


def _strip_prefix(heading: str) -> str:
    """Remove university/course name prefixes to get the meaningful heading.

    E.g.  "Sharda University Online MBA Admission Process"  →  "Admission Process"
    """
    stripped = _PREFIX_STRIP_RE.sub("", heading).strip()
    # If the regex ate the entire heading, fall back to the original
    return stripped if stripped else heading.strip()


def _is_heading(para) -> bool:
    """Return True if *para* looks like a section heading."""
    # 1. Style-based detection
    if para.style and para.style.name:
        name = para.style.name
        if "Heading" in name or "Title" in name:
            return True

    # 2. Font-based heuristic: all runs bold and largest font ≥ 14 pt
    runs_with_text = [r for r in para.runs if r.text.strip()]
    if not runs_with_text:
        return False

    all_bold = all(_run_is_bold(r) for r in runs_with_text)
    if not all_bold:
        return False

    max_pt = 0.0
    for r in runs_with_text:
        size = r.font.size
        if size is not None:
            pt_val = size.pt
            if pt_val > max_pt:
                max_pt = pt_val
    if max_pt >= 14:
        return True

    return False


def _run_is_bold(run) -> bool:
    """Check if a run is bold, accounting for inherited styles."""
    if run.bold is True:
        return True
    if run.bold is None:
        # May inherit from style — check the character style
        try:
            style = run.style
            if style and style.font and style.font.bold:
                return True
        except Exception:
            pass
    return False


def _detect_and_format(
    content: list[dict[str, Any]],
) -> tuple[str, Any]:
    """Determine the content type and return (type_label, formatted_content).

    Returns one of:
      - ("faq", [{"question": str, "answer": str}, ...])
      - ("table", [{"headers": [...], "rows": [[...], ...]}, ...])
      - ("bullet", [str, ...])
      - ("paragraph", str)                 — joined HTML paragraphs
      - ("mixed", {"paragraphs": str, "tables": [...]})
    """
    paragraphs = [item for item in content if item["type"] == "paragraph"]
    tables = [item for item in content if item["type"] == "table"]

    texts = [p["text"] for p in paragraphs]

    # ── FAQ detection ──
    if len(texts) >= 2:
        if _looks_like_faq(texts):
            faq_items = _build_faq(texts)
            if faq_items:
                return ("faq", faq_items)

    # ── Pure table ──
    if tables and not paragraphs:
        formatted_tables = _format_tables(tables)
        return ("table", formatted_tables)

    # ── Bullet detection ──
    if texts:
        bullet_count = sum(1 for t in texts if _BULLET_RE.match(t))
        ratio = bullet_count / len(texts) if texts else 0
        if ratio >= 0.6 or (len(texts) >= 3 and bullet_count == len(texts)):
            cleaned = [_BULLET_RE.sub("", t).strip() for t in texts]
            return ("bullet", cleaned)

    # ── Mixed (paragraphs + tables) ──
    if tables and paragraphs:
        html_body = _texts_to_html(texts)
        formatted_tables = _format_tables(tables)
        return (
            "mixed",
            {"paragraphs": html_body, "tables": formatted_tables},
        )

    # ── Plain paragraph(s) ──
    if texts:
        html_body = _texts_to_html(texts)
        return ("paragraph", html_body)

    return ("paragraph", "")


def _looks_like_faq(texts: list[str]) -> bool:
    """Return True if the text list looks like alternating Q/A pairs."""
    if len(texts) < 2:
        return False

    # Strategy 1: even-length list, every even-indexed item (0, 2, 4, …) ends with "?"
    if len(texts) % 2 == 0:
        question_indices = range(0, len(texts), 2)
        if all(texts[i].rstrip().endswith("?") for i in question_indices):
            return True

    # Strategy 2: at least 40 % of items end with "?" (mixed format)
    q_count = sum(1 for t in texts if t.rstrip().endswith("?"))
    if q_count >= 2 and q_count / len(texts) >= 0.35:
        return True

    return False


def _build_faq(texts: list[str]) -> list[dict[str, str]]:
    """Build FAQ list from alternating Q/A text items."""
    faq: list[dict[str, str]] = []
    i = 0
    while i < len(texts):
        question = texts[i].strip()
        if question.endswith("?"):
            answer = texts[i + 1].strip() if i + 1 < len(texts) else ""
            faq.append({"question": question, "answer": answer})
            i += 2
        else:
            # Non-question item encountered — try to absorb into previous answer
            if faq:
                faq[-1]["answer"] += " " + question
            i += 1
    return faq


def _format_tables(
    tables: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Normalise raw table dicts into {headers, rows}."""
    out: list[dict[str, Any]] = []
    for tbl in tables:
        rows = tbl["rows"]
        if not rows:
            continue
        headers = rows[0]
        data_rows = rows[1:] if len(rows) > 1 else []
        out.append({"headers": headers, "rows": data_rows})
    return out


def _texts_to_html(texts: list[str]) -> str:
    """Wrap plain text items in <p> tags to produce simple HTML."""
    parts: list[str] = []
    for t in texts:
        escaped = (
            t.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        parts.append(f"<p>{escaped}</p>")
    return "\n".join(parts)
