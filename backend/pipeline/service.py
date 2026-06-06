"""
Shared extraction pipeline service.

Single source of truth for the full extraction pipeline, used by both
the FastAPI ``/upload`` endpoint and the background bulk-processing task.

Pipeline stages
---------------
1. Parse DOCX → section map
2. Detect page type
3. Embed headings → match to ACF fields
4. Score-route → AI confirm/resolve  (two-pass: route then extract)
5. Extract field content via Claude
6. Enrich payload via regex (no API)
7. Validate
8. Persist to database
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from db.models import Upload, FieldMapping
from pipeline.docx_parser import parse_docx
from pipeline.page_detector import detect_page_type
from pipeline.embedder import match_headings_to_fields, initialize_field_index
from pipeline.extractor import extract_field, confirm_mapping, resolve_ambiguous
from pipeline.enricher import enrich_payload
from pipeline.validator import validate_payload
from pipeline.kv_parser import looks_like_kv_section, parse_kv_section, flatten_section_to_text
from pipeline.classifier import classify_heading, VALID_ACF_FIELDS
from schemas import FIELD_TYPES_BY_TYPE

logger = logging.getLogger("degreebaba.pipeline")

# ────────────────────────── confidence thresholds ──────────────────────────

THRESHOLD_AUTO = 0.78      # Auto-accept — no LLM confirmation needed
THRESHOLD_VERIFY = 0.60    # Send to LLM for confirmation
THRESHOLD_FALLBACK = 0.42  # Send to LLM with all 3 candidates
# Below THRESHOLD_FALLBACK → flag as UNMAPPED / skip

# ────────────────────────── critical field thresholds ──────────────────────────

# Critical patterns: heading substrings that must never be silently dropped.
# These fields are too important to miss; they get a lower drop threshold so
# they are always sent to the LLM resolution path.
_CRITICAL_THRESHOLD_MAP: dict[str, float] = {
    # Semantically unmistakable single-word section identifiers
    # These score low purely because prefix noise wasn't fully stripped
    "faq":           0.20,
    "review":        0.20,
    "syllabus":      0.25,
    "curriculum":    0.25,
    "exam":          0.25,    # examination process, exam pattern
    "examination":   0.25,
    "about":         0.28,    # about the course / university
    "admission":     0.28,
    "eligibility":   0.28,
    "fee":           0.28,
    "emi":           0.28,
    "placement":     0.28,
    "faculty":       0.28,
    "fact":          0.30,    # course facts, quick facts
    "highlight":     0.30,
    "accreditation": 0.30,
    "pros":          0.30,    # pros / advantages / benefits
    "benefit":       0.30,
    "advantage":     0.30,
    "detail":        0.30,    # details / info sections
    "description":   0.30,
    "course":        0.30,    # courses table
    "program":       0.30,
}


def get_effective_threshold(stripped_heading: str) -> float:
    """Return the drop threshold for a given (already-stripped) heading.

    Critical patterns get a much lower threshold so they are always sent
    to the LLM resolution path rather than silently dropped.
    """
    lower = stripped_heading.lower()
    for pattern, threshold in _CRITICAL_THRESHOLD_MAP.items():
        if pattern in lower:
            return threshold
    return THRESHOLD_FALLBACK


# ────────────────────────── length correction ──────────────────────────


def apply_length_correction(score: float, heading: str) -> float:
    """Boost cosine similarity for longer headings.

    Cosine similarity naturally drops for longer text embeddings.
    A 6-word heading that clearly maps to a field should not be penalised.
    This correction boosts scores proportionally to heading length.
    """
    word_count = len(heading.split())
    if word_count <= 3:
        return score               # no correction needed
    elif word_count <= 5:
        return min(score * 1.05, 1.0)   # +5% boost
    elif word_count <= 8:
        return min(score * 1.12, 1.0)   # +12% boost
    else:
        return min(score * 1.18, 1.0)   # +18% boost for very long headings


# ────────────────────────── public API ──────────────────────────


def run_extraction_pipeline(
    file_bytes: bytes,
    filename: str,
    forced_page_type: str | None,
    db: Session,
) -> dict[str, Any]:
    """Execute the full extraction pipeline and persist results.

    This is the **single implementation** of the pipeline.  Both the
    ``/upload`` endpoint and the background ``run_bulk_job_in_background`` task
    delegate here.

    Parameters
    ----------
    file_bytes : bytes
        Raw ``.docx`` file bytes.
    filename : str
        Original filename for the upload record.
    forced_page_type : str | None
        Forced page type, or ``None`` to auto-detect.
    db : Session
        SQLAlchemy session for persistence.

    Returns
    -------
    dict
        Complete result dict with ``upload_id``, ``payload``,
        ``validation``, ``field_mappings``, and ``processing_time_ms``.
    """
    t0 = time.time()

    # ── Step 1: Parse DOCX ──
    parser_output = parse_docx(file_bytes)
    # Support both old schema and new schema (which wraps in "sections")
    section_map = parser_output.get("sections", parser_output) if isinstance(parser_output, dict) else parser_output
    section_headings = [k for k in section_map if not k.startswith("__")]
    logger.info(
        "PARSED %d sections from %s: %s",
        len(section_headings), filename, section_headings,
    )

    # ── Step 2: Detect page type ──
    detected_type = forced_page_type or detect_page_type(section_map)
    logger.info(
        "PAGE_TYPE: %s (forced=%s)",
        detected_type, forced_page_type is not None,
    )

    # ── Step 2.5: KV pre-pass — intercept key-value metadata sections ──
    # Some sections contain "Key - Value" pairs that map to MULTIPLE fields.
    # Detect and parse them directly; remove from section_map so they are
    # not double-processed by the embedding path.
    kv_payload: dict[str, Any] = {}
    kv_records: list[dict[str, Any]] = []
    kv_headings_to_remove: list[str] = []

    for heading, section_data in list(section_map.items()):
        if heading.startswith("__"):
            continue
        raw_content = flatten_section_to_text(section_data.get("content", ""))
        if not raw_content or not looks_like_kv_section(raw_content):
            continue

        kv_fields = parse_kv_section(raw_content)
        if not kv_fields:
            continue

        # Only remove from section_map if we extracted ≥ 1 field
        kv_headings_to_remove.append(heading)
        for kv in kv_fields:
            fkey = kv["field_key"]
            # Don't overwrite a value that came from a more specific section
            if fkey not in kv_payload:
                kv_payload[fkey] = kv["value"]
                kv_records.append({
                    "field_key":      fkey,
                    "heading_in_doc": heading,
                    "value":          str(kv["value"]),
                    "confidence":     kv["confidence"],
                    "status":         "mapped",
                    "source":         "KV",
                })

    for h in kv_headings_to_remove:
        logger.info(
            "KV_SECTION: removed %r from embedding pass (%d fields extracted)",
            h, sum(1 for r in kv_records if r["heading_in_doc"] == h),
        )

    # ── Step 2.75: Classify Headings (Three-Tier Mapping) ──
    direct_assignments: list[dict[str, Any]] = []
    sections_for_embedding: dict[str, dict[str, Any]] = {}

    for heading, section_data in list(section_map.items()):
        if heading.startswith("__"):
            sections_for_embedding[heading] = section_data
            continue

        result = classify_heading(heading, VALID_ACF_FIELDS)
        section_data["classification"] = result
        section_data["display_heading"] = result["display"]

        if result["route"] == "direct":
            # TIER 1 — skip embedding entirely
            direct_assignments.append({
                "heading": heading,
                "content": section_data.get("content", section_data),
                "field_key": result["field_key"],
                "confidence": 1.0,
                "source": "tagged",
                "tier": 1,
            })
        else:
            # TIER 2 or 3 — use embed_heading for embedding
            section_data["heading_for_embedding"] = result["embed_heading"]
            sections_for_embedding[heading] = section_data

    # ── Step 3: Match headings → fields ──
    initialize_field_index()
    matches = match_headings_to_fields(sections_for_embedding, detected_type)
    field_types = FIELD_TYPES_BY_TYPE.get(detected_type, {})

    # ── Step 4: Two-pass score routing + extraction ──
    #   Pass 1 — choose best field per heading, resolve duplicates
    assignments = _route_headings(matches, detected_type)

    #   Pass 1.5 — Merge Tier 1 (direct_assignments) into assignments
    for da in direct_assignments:
        assignments[da["field_key"]] = {
            "heading": da["heading"],
            "content": da["content"],
            "confidence": da["confidence"],
            "source": da["source"],
            "content_len": len(str(da["content"])),
        }

    logger.info(
        "ASSIGNMENTS: %d fields assigned (%d direct, %d routed)",
        len(assignments), len(direct_assignments), len(assignments) - len(direct_assignments),
    )

    #   Pass 2 — extract content for each assigned field (Claude calls)
    payload, mapping_records = _extract_assignments(assignments, field_types)

    # ── Merge KV pre-pass results (fills gaps not covered by LLM) ──
    for fkey, fval in kv_payload.items():
        if payload.get(fkey) is None:
            payload[fkey] = fval
            logger.info("KV_MERGED: %s = %r", fkey, str(fval)[:120])
    # KV records always appended (even if superseded by LLM, keeps audit trail)
    mapping_records.extend(kv_records)

    # ── Step 5: Enrich payload (regex, zero API calls) ──
    payload, enrichment_log = enrich_payload(payload, section_map, detected_type, filename=filename)

    # Record enrichment results as mapping entries
    for entry in enrichment_log:
        if entry["status"] == "enriched":
            enriched_value = payload.get(entry["field_key"])
            db_value = enriched_value
            if enriched_value is not None and not isinstance(enriched_value, str):
                db_value = json.dumps(enriched_value, ensure_ascii=False)
            mapping_records.append({
                "field_key": entry["field_key"],
                "heading_in_doc": f"[enriched from {entry['source']}]",
                "value": db_value,
                "confidence": 0.95,
                "status": "mapped",
                "source": "ENRICHED",
            })

    # ── Step 6: Validate ──
    validation = validate_payload(payload, detected_type)
    quality_score = validation["summary"]["quality_score"]

    # Diagnostic log for non-mapped fields
    for fr in validation["field_report"]:
        if fr["status"] != "mapped":
            logger.warning(
                "FIELD_ISSUE: %s status=%s has_value=%s",
                fr["field_key"], fr["status"], fr["has_value"],
            )

    logger.info(
        "VALIDATION: score=%.2f mapped=%d thin=%d missing=%d",
        quality_score,
        validation["summary"]["mapped"],
        validation["summary"]["thin"],
        validation["summary"]["missing"],
    )

    # ── Step 7: Persist ──
    upload = Upload(
        filename=filename,
        page_type=detected_type,
        status="processed",
        score=quality_score,
        payload=json.dumps(payload, ensure_ascii=False),
    )
    db.add(upload)
    db.flush()  # get upload.id

    for rec in mapping_records:
        fm = FieldMapping(upload_id=upload.id, **rec)
        db.add(fm)

    db.commit()
    db.refresh(upload)

    elapsed_ms = round((time.time() - t0) * 1000, 1)
    logger.info(
        "PIPELINE_COMPLETE: id=%d file=%s score=%.2f time=%.1fms",
        upload.id, filename, quality_score, elapsed_ms,
    )

    return {
        "upload_id": upload.id,
        "filename": filename,
        "page_type": detected_type,
        "payload": payload,
        "validation": validation,
        "field_mappings": [
            {
                "field_key": r["field_key"],
                "heading_in_doc": r["heading_in_doc"],
                "confidence": r["confidence"],
                "status": r["status"],
                "source": r["source"],
            }
            for r in mapping_records
        ],
        "processing_time_ms": elapsed_ms,
    }


# ────────────────────────── internal helpers ──────────────────────────


def _route_headings(
    matches: list[dict[str, Any]],
    detected_type: str,
) -> dict[str, dict[str, Any]]:
    """Pass 1 — score-route each heading and resolve duplicates.

    Returns a dict mapping ``field_key`` → assignment metadata::

        {"heading", "content", "confidence", "source", "content_len"}

    Improvements over the legacy single-pass approach:

    * **Duplicate resolution**: if two headings map to the same field,
      the one with higher confidence (or larger content on tie) wins.
    * **Rejection fallback**: when ``confirm_mapping()`` rejects the
      best candidate, the next candidate with score ≥ 0.72 is accepted
      deterministically (no additional API call).
    * **Comprehensive logging** for every routing decision.
    """
    assignments: dict[str, dict[str, Any]] = {}

    for match in matches:
        raw_best_score: float = match["best_score"]
        heading: str = match["heading"]
        content: Any = match["content"]
        candidates: list[dict[str, Any]] = match["matches"]

        # Apply length correction to all candidate scores
        corrected_candidates = []
        for c in candidates:
            corrected = apply_length_correction(c["score"], heading)
            corrected_candidates.append({**c, "score": corrected})
        corrected_candidates.sort(key=lambda x: x["score"], reverse=True)

        best_score = corrected_candidates[0]["score"] if corrected_candidates else 0.0
        best_field: str = corrected_candidates[0]["field_key"] if corrected_candidates else ""

        chosen_field: str | None = None
        source = "embedding"
        confidence = best_score

        # ── Score routing ──

        if best_score >= THRESHOLD_AUTO:
            # High confidence — accept directly, no LLM needed
            chosen_field = best_field
            logger.info(
                "AUTO_ACCEPT: heading=%r → %s (score=%.4f)",
                heading, best_field, best_score,
            )

        elif best_score >= THRESHOLD_VERIFY:
            # Medium confidence — confirm with AI
            try:
                confirmation = confirm_mapping(
                    heading, content, best_field, detected_type
                )
                if confirmation.get("confirmed"):
                    chosen_field = best_field
                    source = "ai"
                    logger.info(
                        "AI_CONFIRMED: heading=%r → %s (score=%.4f)",
                        heading, best_field, best_score,
                    )
                else:
                    # Rejection fallback: try next candidates deterministically
                    for candidate in corrected_candidates[1:]:
                        cand_score = candidate["score"]
                        if cand_score >= THRESHOLD_VERIFY:
                            chosen_field = candidate["field_key"]
                            confidence = cand_score
                            source = "embedding_fallback"
                            logger.info(
                                "FALLBACK: heading=%r rejected best=%s(%.4f),"
                                " using %s(%.4f)",
                                heading, best_field, best_score,
                                chosen_field, cand_score,
                            )
                            break
                    if chosen_field is None:
                        logger.info(
                            "REJECTED: heading=%r — best=%s rejected, "
                            "no fallback candidates ≥ %.2f",
                            heading, best_field, THRESHOLD_VERIFY,
                        )
            except Exception as exc:
                logger.warning(
                    "confirm_mapping failed for %r: %s", heading, exc
                )
                chosen_field = best_field  # fallback on API error

        elif best_score >= THRESHOLD_FALLBACK or best_score >= get_effective_threshold(heading):
            # Low confidence — resolve with AI using all candidates
            try:
                resolution = resolve_ambiguous(
                    heading, content, corrected_candidates, detected_type
                )
                chosen_field = resolution.get("field_key")
                confidence = resolution.get("confidence", 0.0)
                source = "ai"
                if chosen_field:
                    logger.info(
                        "AI_RESOLVED: heading=%r → %s (confidence=%.4f)",
                        heading, chosen_field, confidence,
                    )
                else:
                    logger.info(
                        "AI_UNRESOLVED: heading=%r — no match", heading
                    )
            except Exception as exc:
                logger.warning(
                    "resolve_ambiguous failed for %r: %s", heading, exc
                )

        else:
            # Below all thresholds — skip
            eff_thresh = get_effective_threshold(heading)
            logger.info(
                "DROPPED: heading=%r best=%s score=%.4f (below %.2f)",
                heading, best_field, best_score, eff_thresh,
            )

        # ── Duplicate resolution ──

        if chosen_field:
            content_len = len(str(content))
            existing = assignments.get(chosen_field)

            if existing:
                replace = False
                if confidence > existing["confidence"]:
                    replace = True
                elif (
                    confidence == existing["confidence"]
                    and content_len > existing["content_len"]
                ):
                    replace = True

                if replace:
                    logger.info(
                        "REPLACING: %s — old=%r(conf=%.4f) → new=%r(conf=%.4f)",
                        chosen_field,
                        existing["heading"], existing["confidence"],
                        heading, confidence,
                    )
                    assignments[chosen_field] = {
                        "heading": heading,
                        "content": content,
                        "confidence": confidence,
                        "source": source,
                        "content_len": content_len,
                    }
                else:
                    logger.info(
                        "DUPLICATE_KEPT: %s — keeping %r(%.4f), "
                        "skipping %r(%.4f)",
                        chosen_field,
                        existing["heading"], existing["confidence"],
                        heading, confidence,
                    )
            else:
                assignments[chosen_field] = {
                    "heading": heading,
                    "content": content,
                    "confidence": confidence,
                    "source": source,
                    "content_len": content_len,
                }

    return assignments


def _extract_assignments(
    assignments: dict[str, dict[str, Any]],
    field_types: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Pass 2 — extract content for each assigned field.

    Returns ``(payload, mapping_records)``.

    Because extraction happens *after* all routing decisions are final,
    each field is extracted exactly once — no wasted API calls from
    duplicate headings.
    """
    payload: dict[str, Any] = {}
    mapping_records: list[dict[str, Any]] = []

    for chosen_field, assignment in assignments.items():
        ft = field_types.get(chosen_field, "wysiwyg")
        heading = assignment["heading"]
        content = assignment["content"]
        confidence = assignment["confidence"]
        source = assignment["source"]

        try:
            extracted = extract_field(chosen_field, ft, content)
        except Exception as exc:
            logger.warning("extract_field(%s) failed: %s", chosen_field, exc)
            extracted = {"value": None, "error": str(exc)}

        value = extracted.get("value")
        payload[chosen_field] = value
        logger.info("EXTRACTED: %s = %s", chosen_field, repr(value)[:200])

        # Serialise non-string values for DB storage
        db_value = value
        if value is not None and not isinstance(value, str):
            db_value = json.dumps(value, ensure_ascii=False)

        # Format source for frontend display
        display_source = source.upper()
        if source == "tagged":
            display_source = "TAGGED"
        elif source == "ai":
            display_source = "AI"
        elif source.startswith("embedding"):
            display_source = "EMBED"
        elif source == "enrichment":
            display_source = "ENRICHED"
        elif source == "kv_parser":
            display_source = "KV"

        mapping_records.append({
            "field_key": chosen_field,
            "heading_in_doc": heading,
            "value": db_value,
            "confidence": confidence,
            "status": "mapped" if value is not None else "missing",
            "source": display_source,
        })

    return payload, mapping_records

