"""
Page-type detector — scores a section map against keyword signals and returns
the most likely page type: "university", "course", or "specialization".
"""

from __future__ import annotations

from typing import Any

# Keyword → score  (each match adds +2)
_UNIVERSITY_SIGNALS: list[str] = [
    "faculty",
    "university facts",
    "accreditation",
    "university courses",
    "pros",
    "emi details",
    "about university",
    "placement partners",
]

_COURSE_SIGNALS: list[str] = [
    "specializations offered",
    "job roles",
    "salary",
    "course facts",
    "about the course",
    "syllabus",
    "fee structure",
    "course details",
]

_SPECIALIZATION_SIGNALS: list[str] = [
    "course details",
    "examination pattern",
    "specialization fee",
    "emi details",
    "about the specialization",
    "specialization highlights",
    "specialization facts",
    "about specialization",
]


def detect_page_type(section_map: dict[str, dict[str, Any]]) -> str:
    """Score the section map headings and return the winning page type.

    Scoring:
        Each heading (lowercased) is checked against every signal keyword
        (also lowercased).  If the keyword appears as a substring of the
        heading, +2 is added to that page type's score.

    Returns one of ``"university"``, ``"course"``, ``"specialization"``.
    Defaults to ``"university"`` on a tie.
    """

    scores: dict[str, int] = {
        "university": 0,
        "course": 0,
        "specialization": 0,
    }

    headings_lower: list[str] = [
        h.lower()
        for h in section_map.keys()
        if not h.startswith("__")  # skip internal keys like __full_html__
    ]

    for heading in headings_lower:
        for kw in _UNIVERSITY_SIGNALS:
            if kw in heading:
                scores["university"] += 2

        for kw in _COURSE_SIGNALS:
            if kw in heading:
                scores["course"] += 2

        for kw in _SPECIALIZATION_SIGNALS:
            if kw in heading:
                scores["specialization"] += 2

    # Resolve winner — university wins ties
    max_score = max(scores.values())
    if max_score == 0:
        return "university"

    # If university ties with another, university wins
    if scores["university"] == max_score:
        return "university"
    if scores["course"] >= scores["specialization"]:
        return "course"
    return "specialization"
