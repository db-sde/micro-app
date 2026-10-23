"""Eval cases on disk: evals/cases/<case_id>/{case.json, doc.docx, truth.json}.

case.json:
    {
      "case_id": "jamia-mba",
      "page_type": "course",                 # university | course | specialization
      "filename": "Copy of Jamia Islamia Online MBA program.docx",   # the title the pipelines see
      "post_id": 1234, "post_type": "course",                       # where truth comes from
      "split": "dev",                        # dev (iterate on) | holdout (final report only)
      "ignore_fields": [],                   # fields not to score for this case
      "truth_overrides": {"field": "value"}, # your review wins over the WordPress value
      "checks": [                            # stress assertions, on the projected page
        {"type": "semester_subjects", "field": "course_academic_years", "equals": [8, 8, 11, 9]},
        {"type": "row_count", "field": "programs_table", "equals": 5},
        {"type": "equals", "field": "spec_name", "value": "Retail Management"},
        {"type": "contains", "field": "admission_steps", "phrases": ["Step 1"]},
        {"type": "not_contains", "field": "placement_content", "phrases": ["guaranteed placement"]},
        {"type": "html_list_items", "field": "admission_steps", "equals": 6},
        {"type": "empty" | "not_empty", "field": "admission_fee_note"}
      ]
    }

truth.json is written by evals.fetch_truth (or by hand / from an export):
    {"post_id", "post_type", "status", "title", "modified", "fetched_at", "acf": {...}}
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).resolve().parent / "cases"
PAGE_TYPES = ("university", "course", "specialization")


@dataclass
class Case:
    case_id: str
    page_type: str
    filename: str
    directory: Path
    post_id: int | None = None
    post_type: str | None = None
    split: str = "dev"
    ignore_fields: list[str] = field(default_factory=list)
    truth_overrides: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)

    @property
    def doc_path(self) -> Path:
        return self.directory / "doc.docx"

    @property
    def truth_path(self) -> Path:
        return self.directory / "truth.json"

    def doc_bytes(self) -> bytes:
        return self.doc_path.read_bytes()

    def truth(self) -> dict[str, Any] | None:
        """WordPress truth with your overrides applied, or None if not fetched yet."""
        if not self.truth_path.exists():
            return None
        data = json.loads(self.truth_path.read_text(encoding="utf-8"))
        acf = dict(data.get("acf") or {})
        acf.update(self.truth_overrides)
        data["acf"] = acf
        return data


def load_case(directory: Path) -> Case:
    spec = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    if spec.get("page_type") not in PAGE_TYPES:
        raise ValueError(f"{directory.name}: page_type must be one of {PAGE_TYPES}")
    return Case(
        case_id=spec.get("case_id") or directory.name,
        page_type=spec["page_type"],
        filename=spec.get("filename") or f"{directory.name}.docx",
        directory=directory,
        post_id=spec.get("post_id"),
        post_type=spec.get("post_type") or spec["page_type"],
        split=spec.get("split", "dev"),
        ignore_fields=list(spec.get("ignore_fields") or []),
        truth_overrides=dict(spec.get("truth_overrides") or {}),
        checks=_merge_checks(spec.get("checks") or [], spec.get("auto_checks") or []),
    )


def _merge_checks(manual: list[dict[str, Any]], auto: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Hand-written checks, plus generated ones (evals/autochecks.py) for anything not already checked by hand."""
    covered = {(c.get("type"), c.get("field")) for c in manual}
    return [*manual, *[c for c in auto if (c.get("type"), c.get("field")) not in covered]]


def load_cases(root: Path = CASES_DIR, ids: list[str] | None = None, split: str = "all") -> list[Case]:
    if not root.exists():
        return []
    cases = [load_case(d) for d in sorted(root.iterdir()) if (d / "case.json").exists()]
    if ids:
        missing = set(ids) - {c.case_id for c in cases}
        if missing:
            raise ValueError(f"Unknown case(s): {sorted(missing)}")
        cases = [c for c in cases if c.case_id in ids]
    if split != "all":
        cases = [c for c in cases if c.split == split]
    return cases


def new_case(case_id: str, docx: Path, page_type: str, post_id: int | None = None, filename: str | None = None,
             split: str = "dev", root: Path = CASES_DIR) -> Path:
    if page_type not in PAGE_TYPES:
        raise ValueError(f"page_type must be one of {PAGE_TYPES}")
    directory = root / case_id
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "doc.docx").write_bytes(Path(docx).read_bytes())
    spec = {"case_id": case_id, "page_type": page_type, "filename": filename or Path(docx).name,
            "post_id": post_id, "post_type": page_type, "split": split,
            "ignore_fields": [], "truth_overrides": {}, "checks": []}
    (directory / "case.json").write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return directory
