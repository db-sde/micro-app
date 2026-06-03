"""
Shared extraction pipeline service.

Single source of truth for the full extraction pipeline, used by both
the FastAPI ``/upload`` endpoint and the Celery bulk-processing task.

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
from schemas import FIELD_TYPES_BY_TYPE

logger = logging.getLogger("degreebaba.pipeline")


# ────────────────────────── public API ──────────────────────────


def run_extraction_pipeline(
    file_bytes: bytes,
    filename: str,
    forced_page_type: str | None,
    db: Session,
) -> dict[str, Any]:
    """Execute the full extraction pipeline and persist results.

    This is the **single implementation** of the pipeline.  Both the
    ``/upload`` endpoint and the Celery ``process_bulk_file`` task
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

    # ── Step 3: Match headings → fields ──
    initialize_field_index()
    matches = match_headings_to_fields(section_map, detected_type)
    field_types = FIELD_TYPES_BY_TYPE.get(detected_type, {})

    # ── Step 4: Two-pass score routing + extraction ──
    #   Pass 1 — choose best field per heading, resolve duplicates
    assignments = _route_headings(matches, detected_type)
    logger.info(
        "ASSIGNMENTS: %d fields assigned from %d headings",
        len(assignments), len(matches),
    )

    #   Pass 2 — extract content for each assigned field (Claude calls)
    payload, mapping_records = _extract_assignments(assignments, field_types)

    # ── Step 5: Enrich payload (regex, zero API calls) ──
    payload, enrichment_log = enrich_payload(payload, section_map, detected_type)

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
                "source": "enrichment",
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
        best_score: float = match["best_score"]
        best_field: str = match["best_field"]
        heading: str = match["heading"]
        content: Any = match["content"]
        candidates: list[dict[str, Any]] = match["matches"]

        chosen_field: str | None = None
        source = "embedding"
        confidence = best_score

        # ── Score routing ──

        if best_score >= 0.88:
            # High confidence — accept directly
            chosen_field = best_field
            logger.info(
                "AUTO_ACCEPT: heading=%r → %s (score=%.4f)",
                heading, best_field, best_score,
            )

        elif best_score >= 0.72:
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
                    # Rejection fallback: try next candidates
                    # deterministically (no additional API call)
                    for candidate in candidates[1:]:
                        cand_score = candidate["score"]
                        if cand_score >= 0.72:
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
                            "no fallback candidates ≥ 0.72",
                            heading, best_field,
                        )
            except Exception as exc:
                logger.warning(
                    "confirm_mapping failed for %r: %s", heading, exc
                )
                chosen_field = best_field  # fallback on API error

        elif best_score >= 0.55:
            # Low confidence — resolve with AI
            try:
                resolution = resolve_ambiguous(
                    heading, content, candidates, detected_type
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
            # Below 0.55 — skip
            logger.info(
                "DROPPED: heading=%r best=%s score=%.4f (below 0.55)",
                heading, best_field, best_score,
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

        mapping_records.append({
            "field_key": chosen_field,
            "heading_in_doc": heading,
            "value": db_value,
            "confidence": confidence,
            "status": "mapped" if value is not None else "missing",
            "source": source,
        })

    return payload, mapping_records
