"""
Celery tasks for background / bulk processing.

Uses Redis as broker.  Falls back gracefully — the main FastAPI app can
run the pipeline synchronously when Celery is unavailable.
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any

from celery import Celery
from dotenv import load_dotenv
import os

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


# ────────────────────────── helpers ──────────────────────────


def _load_job_results(job) -> list[dict]:
    """Parse existing results JSON from a BulkJob record."""
    if not job.results:
        return []
    try:
        return json.loads(job.results)
    except json.JSONDecodeError:
        return []


# ────────────────────────── tasks ──────────────────────────


@celery_app.task(bind=True, name="process_bulk_file", max_retries=1)
def process_bulk_file(
    self,
    job_id: int,
    file_bytes_hex: str,
    filename: str,
    page_type: str | None = None,
) -> dict[str, Any]:
    """Process a single .docx file as part of a bulk job.

    Delegates all extraction logic to :func:`pipeline.service.run_extraction_pipeline`
    and only handles the BulkJob progress bookkeeping here.

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
        Per-file result summary with ``status``, ``upload_id``,
        ``quality_score``, and optional ``error``.
    """
    # Import here to avoid circular imports at module level
    from db.database import SessionLocal
    from db.models import BulkJob
    from pipeline.service import run_extraction_pipeline

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

        # ── Delegate to the shared pipeline service ──
        pipeline_result = run_extraction_pipeline(
            file_bytes, filename, page_type, db
        )

        result["status"] = "success"
        result["upload_id"] = pipeline_result["upload_id"]
        result["quality_score"] = pipeline_result["validation"]["summary"][
            "quality_score"
        ]

        # ── Update bulk job progress ──
        job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
        if job:
            job.processed_files = (job.processed_files or 0) + 1

            existing_results = _load_job_results(job)
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

        # Still try to update the job progress so the UI stays consistent
        try:
            job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
            if job:
                job.processed_files = (job.processed_files or 0) + 1
                existing_results = _load_job_results(job)
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
