"""
Embedding-based heading→field matcher using OpenAI text-embedding-3-large.

Public API
----------
initialize_field_index()       — pre-compute embeddings for all field descriptions (call once at startup)
match_headings_to_fields(…)    — embed document headings and cosine-match them against the field index
"""

from __future__ import annotations

import os
import logging
from typing import Any

import numpy as np
from openai import OpenAI
from dotenv import load_dotenv

from acf.fields import ACF_FIELDS

load_dotenv()
logger = logging.getLogger(__name__)

# ────────────────────────── module state ──────────────────────────

_client: OpenAI | None = None
_MODEL = "text-embedding-3-large"

# {page_type: {field_key: {"description": str, "vector": np.ndarray}}}
_field_index: dict[str, dict[str, dict[str, Any]]] = {}
_initialized: bool = False

_ALL_FIELDS: dict[str, dict[str, str]] = {}
for page_type, fields_list in ACF_FIELDS.items():
    _ALL_FIELDS[page_type] = {
        f["key"]: f["embed"] for f in fields_list
        if not f["key"].endswith("_heading")
    }


import re

# ────────────────────────── helpers ──────────────────────────

def _is_exact_match(heading: str, field_key: str, field_embed_str: str) -> bool:
    """Check if the heading contains the exact field name or a primary synonym."""
    h_lower = heading.lower()
    
    # 1. Field key base
    core_key = field_key.replace('_content', '').replace('_table', '').replace('_members', '')
    core_key = core_key.replace('_plans', '').replace('_profiles', '').replace('_steps', '')
    core_key = core_key.replace('_intro', '')
    core_key = core_key.replace('_', ' ')
    
    if len(core_key) > 3 and re.search(rf'\b{re.escape(core_key)}\b', h_lower):
        return True
        
    # 2. First 1-3 words of the embed string (usually the exact synonym, e.g. "why choose")
    embed_words = field_embed_str.split()
    if len(embed_words) >= 1 and len(embed_words[0]) > 3:
        if re.search(rf'\b{re.escape(embed_words[0])}\b', h_lower):
            return True
    if len(embed_words) >= 2:
        two_words = f"{embed_words[0]} {embed_words[1]}"
        if len(two_words) > 5 and re.search(rf'\b{re.escape(two_words)}\b', h_lower):
            return True
    if len(embed_words) >= 3:
        three_words = f"{embed_words[0]} {embed_words[1]} {embed_words[2]}"
        if len(three_words) > 8 and re.search(rf'\b{re.escape(three_words)}\b', h_lower):
            return True
            
    return False

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key or api_key.startswith("your_"):
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Please add it to .env."
            )
        _client = OpenAI(api_key=api_key)
    return _client


def embed_texts(texts: list[str]) -> list[np.ndarray]:
    """Batch-embed a list of texts using OpenAI text-embedding-3-large.

    Returns a list of numpy vectors (one per input text).
    Raises RuntimeError if the API call fails.
    """
    if not texts:
        return []

    client = _get_client()

    # print(f"Embedding {len(texts)} texts with OpenAI …", texts)

    # OpenAI allows up to 2048 inputs per call — well above what we need
    try:
        response = client.embeddings.create(model=_MODEL, input=texts)
    except Exception as exc:
        raise RuntimeError(f"OpenAI embedding call failed: {exc}") from exc

    # Sort by index to guarantee order matches input
    sorted_data = sorted(response.data, key=lambda d: d.index)
    # print([np.array(d.embedding, dtype=np.float64) for d in sorted_data])
    return [np.array(d.embedding, dtype=np.float64) for d in sorted_data]


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


# ────────────────────────── public API ──────────────────────────


def initialize_field_index() -> None:
    """Embed all field descriptions and cache the vectors.

    Safe to call multiple times — only runs the embedding once.
    """
    global _field_index, _initialized

    if _initialized:
        logger.info("Field index already initialised — skipping.")
        return

    logger.info("Initialising field embedding index …")

    for page_type, fields in _ALL_FIELDS.items():
        descriptions = list(fields.values())
        keys = list(fields.keys())

        vectors = embed_texts(descriptions)

        _field_index[page_type] = {}
        for key, desc, vec in zip(keys, descriptions, vectors):
            _field_index[page_type][key] = {
                "description": desc,
                "vector": vec,
            }

        logger.info(
            "  %s: embedded %d field descriptions", page_type, len(keys)
        )

    _initialized = True
    logger.info("Field embedding index ready.")


def match_headings_to_fields(
    section_map: dict[str, dict[str, Any]],
    page_type: str,
) -> list[dict[str, Any]]:
    """Match document headings to ACF fields via cosine similarity.

    Parameters
    ----------
    section_map : dict
        Output of ``parse_docx``.
    page_type : str
        One of ``"university"``, ``"course"``, ``"specialization"``.

    Returns
    -------
    list[dict]
        One entry per heading::

            {
                "heading": str,
                "section_type": str,        # paragraph / bullet / table / …
                "content": Any,
                "matches": [
                    {"field_key": str, "score": float},
                    …                       # top 3
                ],
                "best_field": str,
                "best_score": float,
            }
    """
    if not _initialized:
        raise RuntimeError(
            "Field index not initialised. Call initialize_field_index() first."
        )

    if page_type not in _field_index:
        raise ValueError(f"Unknown page type: {page_type!r}")

    field_idx = _field_index[page_type]

    # Support new parser structure where sections are inside "sections" key
    if "sections" in section_map and "__meta__" in section_map:
        sections_dict = section_map["sections"]
    else:
        sections_dict = section_map

    # Collect headings to embed (skip internal keys)
    original_headings: list[str] = []
    headings_to_embed: list[str] = []

    for h, section_data in sections_dict.items():
        if h.startswith("__"):
            continue
        original_headings.append(h)
        headings_to_embed.append(section_data.get("heading_for_embedding", h))

    if not headings_to_embed:
        print("No headings found in document — skipping embedding.")
        return []
    print(headings_to_embed)

    heading_vectors = embed_texts(headings_to_embed)

    results: list[dict[str, Any]] = []

    for heading, h_vec in zip(original_headings, heading_vectors):
        # Score against every field
        scored: list[dict[str, Any]] = []
        for field_key, field_data in field_idx.items():
            sim = cosine_similarity(h_vec, field_data["vector"])
            
            if _is_exact_match(heading, field_key, field_data["description"]):
                sim = 1.0  # Exact match overrides embedding score
                
            scored.append({"field_key": field_key, "score": min(round(sim, 4), 1.0)})

        # Sort descending by score
        scored.sort(key=lambda x: x["score"], reverse=True)
        top3 = scored[:3]

        section_data = sections_dict[heading]
        # Handle both old schema ("type") and new schema ("content_type")
        content_type = section_data.get("content_type") or section_data.get("type", "unknown")

        results.append(
            {
                "heading": heading,
                "original_heading": section_data.get("heading_original", heading),
                "section_type": content_type,
                "content": section_data.get("content", section_data),
                "matches": top3,
                "best_field": top3[0]["field_key"] if top3 else "",
                "best_score": top3[0]["score"] if top3 else 0.0,
            }
        )
    print("Matched headings to fields:", results)
    return results
