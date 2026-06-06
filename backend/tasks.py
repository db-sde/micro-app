"""
Background tasks for bulk processing.

Uses FastAPI's built-in BackgroundTasks to process bulk files sequentially
in the background without external message brokers like Celery or Redis.
"""

from __future__ import annotations

import json
import logging
import traceback
from typing import Any

from db.database import SessionLocal
from db.models import BulkJob
from pipeline.service import run_extraction_pipeline

logger = logging.getLogger(__name__)


def _load_job_results(job) -> list[dict]:
    """Parse existing results JSON from a BulkJob record."""
    if not job.results:
        return []
    try:
        return json.loads(job.results)
    except json.JSONDecodeError:
        return []


def run_bulk_job_in_background(
    job_id: int,
    docx_entries: list[tuple[str, bytes]],
    page_type: str | None = None,
) -> None:
    """Process a list of .docx files as part of a bulk job sequentially in the background.

    Delegates extraction logic to :func:`pipeline.service.run_extraction_pipeline`
    and handles the BulkJob progress bookkeeping in the database.
    """
    db = SessionLocal()
    try:
        results: list[dict[str, Any]] = []

        # Make sure the job exists and status is set to processing
        job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
        if not job:
            logger.error("Bulk job %d not found in background task", job_id)
            return

        job.status = "processing"
        db.commit()

        for filename, file_bytes in docx_entries:
            result: dict[str, Any] = {
                "filename": filename,
                "status": "failed",
                "error": None,
                "upload_id": None,
                "quality_score": 0.0,
            }

            try:
                # Run the extraction pipeline
                pipeline_result = run_extraction_pipeline(
                    file_bytes, filename, page_type, db
                )

                result["status"] = "success"
                result["upload_id"] = pipeline_result["upload_id"]
                result["quality_score"] = pipeline_result["validation"]["summary"][
                    "quality_score"
                ]

                # Update progress
                job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
                if job:
                    job.processed_files = (job.processed_files or 0) + 1
                    existing_results = _load_job_results(job)
                    existing_results.append(result)
                    job.results = json.dumps(existing_results, ensure_ascii=False)
                    if job.processed_files >= job.total_files:
                        job.status = "completed"
                    db.commit()

            except Exception as exc:
                db.rollback()
                logger.error("Bulk file processing failed for %s: %s", filename, exc)
                result["error"] = traceback.format_exc()

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
                except Exception as inner_exc:
                    db.rollback()
                    logger.error("Failed to update bulk job status after error: %s", inner_exc)

        # Final check if job status is completed
        job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
        if job and job.status == "processing":
            existing_results = _load_job_results(job)
            all_success = all(r.get("status") == "success" for r in existing_results)
            job.status = "completed" if all_success else "completed_with_errors"
            db.commit()

    except Exception as exc:
        logger.error("Unexpected error in bulk job %d: %s", job_id, exc)
    finally:
        db.close()
