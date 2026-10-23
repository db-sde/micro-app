"""Extraction v2: .docx -> Markdown (Docling's Word backend, docx_parser fallback)."""

from __future__ import annotations

import pytest

from pipeline.v2 import markdown as md
from tests.v2_helpers import upes_course_docx

pytest.importorskip("docling", reason="docling-slim[format-docx] is in requirements.txt")


@pytest.fixture(scope="module")
def doc():
    return md.to_markdown(upes_course_docx(), "Copy of UPES Online MBA program.docx")


def test_docling_is_used(doc) -> None:
    assert doc.parser == "docling" and doc.error is None
    assert doc.title == "Copy of UPES Online MBA program"


def test_writer_tags_and_linked_lines_stay_verbatim(doc) -> None:
    assert "[about_heading] About UPES Online MBA" in doc.markdown
    assert "Linked_university - UPES Online" in doc.markdown
    assert "\\_" not in doc.markdown


def test_bold_step_lines_stay_inside_the_admission_section(doc) -> None:
    """v1 split these into their own sections, so the UPES steps were lost."""
    section = doc.markdown.split("[admission_heading]")[1].split("\n#")[0]
    assert "**Step 1. Ensure your eligibility:** Students are required" in section
    assert "**Step 2. Register online:**" in section
    assert "**Additional information:**" in section
    assert "# Step" not in doc.markdown


def test_tables_keep_every_row_and_cell_line_breaks(doc) -> None:
    assert "| Sales and Marketing" in doc.markdown
    assert "Accounting<br>Economics" in doc.markdown
    fee_table = doc.tables[0]
    assert fee_table[0] == ["Specializations", "Fee"]
    assert fee_table[2] == ["Sales and Marketing", "INR 40,000 /- Semester"]
    assert doc.tables[1][1] == ["Accounting\nEconomics", "Marketing\nFinance"]


def test_fallback_when_docling_fails(monkeypatch) -> None:
    def broken(*_a, **_k):
        raise RuntimeError("converter crashed")

    monkeypatch.setattr(md, "_docling", broken)
    doc = md.to_markdown(upes_course_docx(), "x.docx")
    assert doc.parser == "fallback"
    assert "converter crashed" in doc.error
    assert "UPES Online MBA Admission Process" in doc.markdown
    assert doc.tables[0][1] == ["Marketing", "INR 25,000 /- Semester"]


def test_a_list_inside_a_table_cell_keeps_one_item_per_line(doc) -> None:
    """Docling renders list cells inline ("- A - B"); subject counts need line breaks."""
    assert "Consumer Behaviour<br>Digital Brand Management" in doc.markdown
    assert doc.markdown.count("Digital Brand Management") == 1  # not repeated outside the table
    assert doc.tables[2][1] == ["Consumer Behaviour\nDigital Brand Management"]
