"""
Page-type detector — scores a section map against weighted keyword signals
and returns the most likely page type: "university", "course", or "specialization".

Scoring tiers
-------------
Tier A (weight 4): Highly discriminating phrases that almost only appear
                   in one particular page type.
Tier B (weight 2): Strong signals that usually indicate a page type.
Tier C (weight 1): Soft signals — useful for tiebreaking.

Tie-breaking
------------
If the top-two types are within MIN_GAP points of each other the result
is considered ambiguous and "university" is returned as the safe default
(callers should prefer a manual page_type override in this case).
"""

from __future__ import annotations

from typing import Any

# ── Tier A — highly discriminating (weight 4) ─────────────────────────────────

_UNI_A: list[str] = [
    "about the university",
    "about university",
    "university highlights",
    "university facts",
    "why choose university",
    "university faculty",
    "placement partners",
    "partner universities",
    "cdoe",
    "affiliated university",
]

_COURSE_A: list[str] = [
    "about the course",
    "about the program",
    "course highlights",
    "course overview",
    "specializations offered",
    "course eligibility",
    "program eligibility",
    "course facts",
    "about mba",
    "about mca",
    "about bba",
    "about bca",
    "about pgdm",
]

_SPEC_A: list[str] = [
    "about the specialization",
    "about specialization",
    "specialization highlights",
    "specialization overview",
    "specialization eligibility",
    "specialization fee",
    "other specializations",
    "explore other specializations",
    "specialization facts",
]

# ── Tier B — strong signals (weight 2) ────────────────────────────────────────

_UNI_B: list[str] = [
    "faculty",
    "accreditation",
    "naac",
    "emi details",
    "placement",
    "about the campus",
    "recognition",
    "approval",
    "ranking",
    "infrastructure",
    "pros of",
    "why choose",
]

_COURSE_B: list[str] = [
    "syllabus",
    "fee structure",
    "fee plans",
    "job roles",
    "job profiles",
    "salary",
    "course details",
    "program details",
    "eligibility criteria",
    "admission process",
    "duration",
    "specialization",
]

_SPEC_B: list[str] = [
    "examination pattern",
    "exam pattern",
    "proctored exam",
    "semester exam",
    "elective",
    "specialization admission",
    "track overview",
]

# ── Tier C — soft / tiebreaker signals (weight 1) ─────────────────────────────

_UNI_C: list[str] = [
    "university",
    "institute",
    "campus",
    "college",
]

_COURSE_C: list[str] = [
    "program",
    "course",
    "degree",
    "curriculum",
    "module",
]

_SPEC_C: list[str] = [
    "specialization",
    "stream",
    "track",
    "elective",
]

# ── Scoring weights ────────────────────────────────────────────────────────────

_SIGNALS: dict[str, list[tuple[list[str], int]]] = {
    "university":     [(_UNI_A, 4),  (_UNI_B, 2),  (_UNI_C, 1)],
    "course":         [(_COURSE_A, 4), (_COURSE_B, 2), (_COURSE_C, 1)],
    "specialization": [(_SPEC_A, 4), (_SPEC_B, 2), (_SPEC_C, 1)],
}

# If top-2 scores are within this gap, the result is ambiguous
MIN_GAP = 3


def detect_page_type(section_map: dict[str, dict[str, Any]]) -> str:
    """Score the section-map headings against weighted keyword signals.

    Parameters
    ----------
    section_map : dict
        Keys are heading strings from the parsed document.

    Returns
    -------
    str
        One of ``"university"``, ``"course"``, ``"specialization"``.
        Falls back to ``"university"`` when the scores are ambiguous or all zero.
    """
    scores: dict[str, int] = {"university": 0, "course": 0, "specialization": 0}

    headings_lower: list[str] = [
        h.lower()
        for h in section_map.keys()
        if not h.startswith("__")  # skip internal sentinel keys
    ]

    for heading in headings_lower:
        for page_type, tier_list in _SIGNALS.items():
            for keywords, weight in tier_list:
                for kw in keywords:
                    if kw in heading:
                        scores[page_type] += weight
                        break  # only score once per tier per heading per type

    # ── Resolve winner ────────────────────────────────────────────────────────
    sorted_types = sorted(scores, key=lambda t: scores[t], reverse=True)
    best, second = sorted_types[0], sorted_types[1]

    best_score = scores[best]
    second_score = scores[second]

    # No signal at all → default university
    if best_score == 0:
        return "university"

    # Ambiguous (gap too small) → safe default is university
    if (best_score - second_score) < MIN_GAP:
        # But if one type is clearly NOT university and both non-uni types
        # agree, trust them over the default.
        if "university" not in (best, second):
            # course vs specialization tie — pick whichever scored higher
            return best
        return "university"

    return best
