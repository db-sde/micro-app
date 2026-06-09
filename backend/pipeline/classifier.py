"""
Three-tier heading classifier for the DegreeBaba pipeline.

Content writers can optionally prefix any heading with ``[field_name]``
to declare exactly which ACF field it belongs to.

Tier 1 — ``[valid_field]`` heading
    Direct map.  Zero embeddings.  100% accurate.

Tier 2 — ``[invalid/typo]`` heading
    Strip the bad tag.  Embed the clean display heading only.
    Better embedding accuracy (less noise in the text).

Tier 3 — No tag at all
    Existing pipeline unchanged.  Embed full heading.
    Backward-compatible with all legacy documents.

Public API
----------
classify_heading(heading, valid_acf_fields) → dict
get_all_valid_field_keys()                  → set[str]
"""

from __future__ import annotations

import re
import logging
from typing import Any

logger = logging.getLogger("degreebaba.classifier")

# Regex: optional leading whitespace, then [tag], then optional display text
_TAG_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(.*)", re.DOTALL)


def classify_heading(heading: str, valid_acf_fields: set[str]) -> dict[str, Any]:
    """Three-tier heading classifier.

    Parameters
    ----------
    heading : str
        Raw heading text from the document (may include ``[field_name]`` prefix).
    valid_acf_fields : set[str]
        Set of all valid ACF field keys (lowercase, underscore-delimited).

    Returns
    -------
    dict with keys:
        route         : ``'direct'`` or ``'embedding'``
        field_key     : str (Tier 1) or None (Tier 2/3)
        display       : str — human-readable heading without the tag
        embed_heading : str (Tier 2/3) or None (Tier 1)
        tag_found     : str — raw tag text if a ``[tag]`` was present, else None
        tier          : 1, 2, or 3

    Examples
    --------
    >>> valid = {'course_name', 'about_content', 'faqs'}
    >>> classify_heading('[course_name] Chandigarh MBA', valid)
    {'route': 'direct', 'field_key': 'course_name', 'display': 'Chandigarh MBA',
     'embed_heading': None, 'tag_found': 'course_name', 'tier': 1}
    >>> classify_heading('[cource_name] Chandigarh MBA', valid)
    {'route': 'embedding', 'field_key': None, 'display': 'Chandigarh MBA',
     'embed_heading': 'Chandigarh MBA', 'tag_found': 'cource_name', 'tier': 2}
    >>> classify_heading('Chandigarh MBA', valid)
    {'route': 'embedding', 'field_key': None, 'display': 'Chandigarh MBA',
     'embed_heading': 'Chandigarh MBA', 'tag_found': None, 'tier': 3}
    """
    heading = heading.strip()
    m = _TAG_RE.match(heading)

    if m:
        raw_tag = m.group(1).strip()
        # Normalise: lowercase + collapse spaces/hyphens to underscores
        tag = raw_tag.lower().replace(" ", "_").replace("-", "_")
        # Display text: the rest of the heading after the tag;
        # fall back to raw_tag itself when the writer put only a tag with no body
        display = m.group(2).strip() or raw_tag

        chosen_tags = []
        if "," in tag:
            parts = [p.strip() for p in tag.split(",")]
            for p in parts:
                if p in valid_acf_fields and not p.endswith("_heading"):
                    chosen_tags.append(p)
            # If no content tags, maybe there are only heading tags. We'll skip adding them, 
            # because _heading tags are auto-populated in service.py anyway.
            if not chosen_tags:
                chosen_tags = [p for p in parts if p in valid_acf_fields]
        else:
            if tag in valid_acf_fields:
                chosen_tags.append(tag)

        if chosen_tags:
            logger.info(
                "TAGGED [T1]: heading=%r → fields=%s (direct, no embedding)",
                heading, chosen_tags,
            )
            return {
                "route":         "direct",
                "field_keys":    chosen_tags,
                "display":       display,
                "embed_heading": None,   # Tier 1 never embeds
                "tag_found":     raw_tag,
                "tier":          1,
            }
        else:
            logger.info(
                "TAGGED [T2]: heading=%r bad_tag=%r → embedding rescue on %r",
                heading, raw_tag, display,
            )
            return {
                "route":         "embedding",
                "field_key":     None,
                "display":       display,
                "embed_heading": display,  # embed the clean display text only
                "tag_found":     raw_tag,
                "tier":          2,
            }

    # No tag found — Tier 3: existing pipeline, embed full heading
    return {
        "route":         "embedding",
        "field_key":     None,
        "display":       heading,
        "embed_heading": heading,  # embed full heading unchanged
        "tag_found":     None,
        "tier":          3,
    }


from acf.fields import get_all_valid_field_keys


# ── Module-level cache — built once, reused for all files ──────────────────
# Import this directly in tasks.py / bulk workers so it is not rebuilt per file.
VALID_ACF_FIELDS: set[str] = get_all_valid_field_keys()
