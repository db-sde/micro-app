"""
Celery tasks for background / bulk processing.

Uses Redis as broker.  Falls back gracefully — the main FastAPI app can run
the pipeline synchronously when Celery is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import traceback
from typing import Any

from celery import Celery
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "degreebaba_tasks",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)


@celery_app.task(bind=True, name="process_bulk_file", max_retries=1)
def process_bulk_file(
    self,
    job_id: int,
    file_bytes_hex: str,
    filename: str,
    page_type: str | None = None,
) -> dict[str, Any]:
    """Process a single .docx file as part of a bulk job.

    Parameters
    ----------
    job_id : int
        The ``BulkJob.id`` to update progress against.
    file_bytes_hex : str
        Hex-encoded file bytes (JSON-safe transport).
    filename : str
        Original filename for the upload record.
    page_type : str | None
        Forced page type, or ``None`` to auto-detect.

    Returns
    -------
    dict
        Per-file result summary.
    """
    # Import here to avoid circular imports at module level
    from db.database import SessionLocal
    from db.models import Upload, FieldMapping, BulkJob
    from pipeline.docx_parser import parse_docx
    from pipeline.page_detector import detect_page_type
    from pipeline.embedder import match_headings_to_fields, initialize_field_index
    from pipeline.extractor import extract_field, confirm_mapping, resolve_ambiguous
    from pipeline.validator import validate_payload
    from schemas import FIELD_TYPES_BY_TYPE

    db = SessionLocal()
    result: dict[str, Any] = {
        "filename": filename,
        "status": "failed",
        "error": None,
        "upload_id": None,
        "quality_score": 0.0,
    }

    try:
        file_bytes = bytes.fromhex(file_bytes_hex)

        # Ensure field index is ready
        initialize_field_index()

        # ── Pipeline ──
        section_map = parse_docx(file_bytes)
        detected_type = page_type or detect_page_type(section_map)
        matches = match_headings_to_fields(section_map, detected_type)
        field_types = FIELD_TYPES_BY_TYPE.get(detected_type, {})

        # Extract content per matched field
        payload: dict[str, Any] = {}
        mapping_records: list[dict[str, Any]] = []

        assigned_fields: set[str] = set()

        for match in matches:
            best_score = match["best_score"]
            best_field = match["best_field"]
            heading = match["heading"]
            content = match["content"]
            candidates = match["matches"]

            chosen_field: str | None = None
            source = "embedding"
            confidence = best_score

            if best_score >= 0.88:
                chosen_field = best_field
            elif best_score >= 0.72:
                confirmation = confirm_mapping(
                    heading, content, best_field, detected_type
                )
                if confirmation.get("confirmed"):
                    chosen_field = best_field
                    source = "ai"
                else:
                    chosen_field = None
            elif best_score >= 0.55:
                resolution = resolve_ambiguous(
                    heading, content, candidates, detected_type
                )
                chosen_field = resolution.get("field_key")
                confidence = resolution.get("confidence", 0.0)
                source = "ai"

            if chosen_field and chosen_field not in assigned_fields:
                ft = field_types.get(chosen_field, "wysiwyg")
                extracted = extract_field(chosen_field, ft, content)
                value = extracted.get("value")
                payload[chosen_field] = value
                assigned_fields.add(chosen_field)

                mapping_records.append(
                    {
                        "field_key": chosen_field,
                        "heading_in_doc": heading,
                        "value": json.dumps(value) if not isinstance(value, str) else value,
                        "confidence": confidence,
                        "status": "mapped" if value is not None else "missing",
                        "source": source,
                    }
                )

        # Validate
        validation = validate_payload(payload, detected_type)
        quality_score = validation["summary"]["quality_score"]

        # ── Persist ──
        upload = Upload(
            filename=filename,
            page_type=detected_type,
            status="processed",
            score=quality_score,
            payload=json.dumps(payload, ensure_ascii=False),
        )
        db.add(upload)
        db.flush()

        for rec in mapping_records:
            fm = FieldMapping(upload_id=upload.id, **rec)
            db.add(fm)

        # Update bulk job progress
        job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
        if job:
            job.processed_files = (job.processed_files or 0) + 1

            # Append to results
            existing_results: list[dict] = []
            if job.results:
                try:
                    existing_results = json.loads(job.results)
                except json.JSONDecodeError:
                    existing_results = []

            result["status"] = "success"
            result["upload_id"] = upload.id
            result["quality_score"] = quality_score
            existing_results.append(result)
            job.results = json.dumps(existing_results, ensure_ascii=False)

            if job.processed_files >= job.total_files:
                job.status = "completed"
            else:
                job.status = "processing"

        db.commit()

    except Exception as exc:
        db.rollback()
        logger.error("Bulk file processing failed for %s: %s", filename, exc)
        result["error"] = traceback.format_exc()

        # Still try to update the job status
        try:
            job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
            if job:
                job.processed_files = (job.processed_files or 0) + 1
                existing_results = []
                if job.results:
                    try:
                        existing_results = json.loads(job.results)
                    except json.JSONDecodeError:
                        existing_results = []
                existing_results.append(result)
                job.results = json.dumps(existing_results, ensure_ascii=False)
                if job.processed_files >= job.total_files:
                    job.status = "completed_with_errors"
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()

    return result
