"""
DegreeBaba Content Publisher — FastAPI application.

Endpoints
---------
POST   /upload               Upload a single .docx and run the full pipeline
POST   /confirm/{upload_id}  Confirm / correct field mappings
GET    /download/{upload_id} Download the ACF JSON payload
POST   /bulk                 Upload a .zip of .docx files for batch processing
GET    /bulk/{job_id}/progress   Check bulk-job progress
GET    /history              List all past uploads
DELETE /history/{upload_id}  Delete an upload
POST   /upload-image         Upload an image associated with an upload
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Depends, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

load_dotenv()

from db.database import Base, engine, get_db
from db.models import Upload, FieldMapping, BulkJob
from pipeline.docx_parser import parse_docx
from pipeline.page_detector import detect_page_type
from pipeline.embedder import match_headings_to_fields, initialize_field_index
from pipeline.extractor import extract_field, confirm_mapping, resolve_ambiguous
from pipeline.validator import validate_payload
from pipeline.service import run_extraction_pipeline

# ────────────────────────── logging ──────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger("degreebaba")

# ────────────────────────── app init ──────────────────────────

app = FastAPI(
    title="DegreeBaba Content Publisher",
    version="1.0.0",
    description="Parse .docx files, map content to WordPress ACF fields, and export JSON payloads.",
)

frontend_url = os.getenv("FRONTEND_URL", "http://localhost:5173")
origins = [origin.strip() for origin in frontend_url.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ────────────────────────── directories ──────────────────────────

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
IMAGE_DIR = UPLOAD_DIR / "images"
IMAGE_DIR.mkdir(exist_ok=True)

# ────────────────────────── startup ──────────────────────────


@app.on_event("startup")
async def startup_event():
    """Create DB tables and initialise the embedding index."""
    logger.info("Creating database tables …")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready.")

    logger.info("Initialising field embedding index …")
    try:
        initialize_field_index()
    except Exception as exc:
        logger.warning(
            "Could not initialise field index (OpenAI key may be missing): %s",
            exc,
        )
    logger.info("Startup complete.")


# ────────────────────────── request / response models ──────────────────────────


class FieldCorrection(BaseModel):
    field_key: str
    heading_in_doc: str


class ConfirmRequest(BaseModel):
    corrections: list[FieldCorrection]


# ────────────────────────── helpers ──────────────────────────


def _run_pipeline(
    file_bytes: bytes,
    filename: str,
    forced_page_type: str | None,
    db: Session,
) -> dict[str, Any]:
    """Execute the full extraction pipeline and persist results.

    Returns a dict suitable for the JSON response.
    """
    return run_extraction_pipeline(file_bytes, filename, forced_page_type, db)
    # NOTE: Legacy pipeline code below is unreachable.
    # Logic has been moved to pipeline/service.py (Parts 1-8 refactoring).
    t0 = time.time()

    # 1. Parse
    section_map = parse_docx(file_bytes)

    # 2. Detect page type
    detected_type = forced_page_type or detect_page_type(section_map)

    # 3. Match headings → fields
    initialize_field_index()
    matches = match_headings_to_fields(section_map, detected_type)
    field_types = FIELD_TYPES_BY_TYPE.get(detected_type, {})

    # 4. Extract content per field (with score-based routing)
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

        # ── Score routing ──
        if best_score >= 0.88:
            # High confidence — accept directly
            chosen_field = best_field
        elif best_score >= 0.72:
            # Medium confidence — confirm with AI
            try:
                confirmation = confirm_mapping(
                    heading, content, best_field, detected_type
                )
                if confirmation.get("confirmed"):
                    chosen_field = best_field
                    source = "ai"
                else:
                    chosen_field = None
            except Exception as exc:
                logger.warning("confirm_mapping failed: %s", exc)
                chosen_field = best_field  # fallback to embedding result
        elif best_score >= 0.55:
            # Low confidence — resolve ambiguity
            try:
                resolution = resolve_ambiguous(
                    heading, content, candidates, detected_type
                )
                chosen_field = resolution.get("field_key")
                confidence = resolution.get("confidence", 0.0)
                source = "ai"
            except Exception as exc:
                logger.warning("resolve_ambiguous failed: %s", exc)
                chosen_field = None
        # Below 0.55 — skip (no match)

        if chosen_field and chosen_field not in assigned_fields:
            ft = field_types.get(chosen_field, "wysiwyg")
            try:
                extracted = extract_field(chosen_field, ft, content)
            except Exception as exc:
                logger.warning("extract_field(%s) failed: %s", chosen_field, exc)
                extracted = {"value": None, "error": str(exc)}

            value = extracted.get("value")
            payload[chosen_field] = value
            assigned_fields.add(chosen_field)

            # Serialise non-string values for DB storage
            db_value = value
            if value is not None and not isinstance(value, str):
                db_value = json.dumps(value, ensure_ascii=False)

            mapping_records.append(
                {
                    "field_key": chosen_field,
                    "heading_in_doc": heading,
                    "value": db_value,
                    "confidence": confidence,
                    "status": "mapped" if value is not None else "missing",
                    "source": source,
                }
            )

    # 5. Validate
    validation = validate_payload(payload, detected_type)
    quality_score = validation["summary"]["quality_score"]

    # 6. Persist
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


# ────────────────────────── endpoints ──────────────────────────


@app.post("/upload")
async def upload_docx(
    file: UploadFile = File(...),
    page_type: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Upload a single .docx file and run the full extraction pipeline."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .docx files are supported. Received: " + file.filename,
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Validate page_type if provided
    if page_type and page_type not in ("university", "course", "specialization"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid page_type: {page_type!r}. Must be university, course, or specialization.",
        )

    try:
        result = _run_pipeline(file_bytes, file.filename, page_type, db)
        return result
    except Exception as exc:
        logger.error("Pipeline failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Pipeline error: {exc}")


@app.post("/confirm/{upload_id}")
async def confirm_fields(
    upload_id: int,
    body: ConfirmRequest,
    db: Session = Depends(get_db),
):
    """Confirm or correct field mappings for an upload.

    Accepts a list of corrections, re-extracts changed fields, and re-validates.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    # Load existing payload
    existing_payload: dict[str, Any] = {}
    if upload.payload:
        try:
            existing_payload = json.loads(upload.payload)
        except json.JSONDecodeError:
            existing_payload = {}

    # Parse the original file to get section content
    # We'll work with field mappings in the DB

    for correction in body.corrections:
        fk = correction.field_key
        heading = correction.heading_in_doc

        # Find or create the field mapping
        fm = (
            db.query(FieldMapping)
            .filter(
                FieldMapping.upload_id == upload_id,
                FieldMapping.field_key == fk,
            )
            .first()
        )

        if fm:
            fm.heading_in_doc = heading
            fm.source = "manual"
            fm.is_confirmed = True
            fm.confidence = 1.0
        else:
            fm = FieldMapping(
                upload_id=upload_id,
                field_key=fk,
                heading_in_doc=heading,
                source="manual",
                is_confirmed=True,
                confidence=1.0,
                status="mapped",
            )
            db.add(fm)

        # If the user provided a new heading, we need to re-extract
        # For manual corrections, the value should be updated separately
        # Mark as confirmed
        fm.status = "mapped"

    # Re-validate the payload
    validation = validate_payload(existing_payload, upload.page_type or "university")
    upload.score = validation["summary"]["quality_score"]
    upload.status = "confirmed"

    db.commit()
    db.refresh(upload)

    # Fetch updated mappings
    mappings = (
        db.query(FieldMapping)
        .filter(FieldMapping.upload_id == upload_id)
        .all()
    )

    return {
        "upload_id": upload.id,
        "status": upload.status,
        "validation": validation,
        "field_mappings": [
            {
                "field_key": m.field_key,
                "heading_in_doc": m.heading_in_doc,
                "confidence": m.confidence,
                "status": m.status,
                "source": m.source,
                "is_confirmed": m.is_confirmed,
            }
            for m in mappings
        ],
    }


@app.get("/download/{upload_id}")
async def download_payload(upload_id: int, db: Session = Depends(get_db)):
    """Download the ACF JSON payload for an upload as a .json file."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    if not upload.payload:
        raise HTTPException(status_code=404, detail="No payload available for this upload.")

    # Build filename
    base = os.path.splitext(upload.filename)[0]
    download_name = f"{base}_acf_payload.json"

    payload_bytes = upload.payload.encode("utf-8")

    return StreamingResponse(
        io.BytesIO(payload_bytes),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{download_name}"',
        },
    )


@app.post("/bulk")
async def bulk_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    dry_run: bool = Form(default=False),
    page_type: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Upload a .zip of .docx files for batch processing.

    Uses background tasks to process files sequentially without blocking the API.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    if not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip files are accepted for bulk upload.")

    if page_type and page_type not in ("university", "course", "specialization"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid page_type: {page_type!r}.",
        )

    zip_bytes = await file.read()
    if not zip_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    # Extract .docx files from zip
    try:
        zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="Invalid zip file.")

    docx_entries: list[tuple[str, bytes]] = []
    for name in zf.namelist():
        if name.lower().endswith(".docx") and not name.startswith("__MACOSX"):
            docx_bytes = zf.read(name)
            docx_entries.append((os.path.basename(name), docx_bytes))

    if not docx_entries:
        raise HTTPException(status_code=400, detail="No .docx files found in the zip archive.")

    # Create bulk job record
    job = BulkJob(
        status="pending",
        total_files=len(docx_entries),
        processed_files=0,
        page_type=page_type,
        dry_run=dry_run,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Import and queue background task
    from tasks import run_bulk_job_in_background
    background_tasks.add_task(
        run_bulk_job_in_background,
        job.id,
        docx_entries,
        page_type,
    )

    return {
        "job_id": job.id,
        "total_files": job.total_files,
        "status": job.status,
        "dry_run": dry_run,
    }


@app.get("/bulk/{job_id}/progress")
async def bulk_progress(job_id: int, db: Session = Depends(get_db)):
    """Check the progress of a bulk processing job."""
    job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Bulk job not found.")

    per_file_results: list[dict] = []
    if job.results:
        try:
            per_file_results = json.loads(job.results)
        except json.JSONDecodeError:
            per_file_results = []

    return {
        "job_id": job.id,
        "status": job.status,
        "total_files": job.total_files,
        "processed_files": job.processed_files,
        "page_type": job.page_type,
        "dry_run": job.dry_run,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "results": per_file_results,
    }


@app.get("/history")
async def list_history(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Return all uploads ordered by most-recent first."""
    uploads = (
        db.query(Upload)
        .order_by(Upload.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    total = db.query(Upload).count()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "uploads": [
            {
                "id": u.id,
                "filename": u.filename,
                "page_type": u.page_type,
                "status": u.status,
                "score": u.score,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in uploads
        ],
    }


@app.delete("/history/{upload_id}")
async def delete_upload(upload_id: int, db: Session = Depends(get_db)):
    """Delete an upload and its associated field mappings (cascade)."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    db.delete(upload)
    db.commit()

    return {"deleted": True, "upload_id": upload_id}


@app.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    upload_id: int = Form(...),
    slot_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Upload an image file associated with a specific upload and slot."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    # Validate image extension
    allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image format: {ext}. Allowed: {', '.join(allowed_extensions)}",
        )

    # Save file
    timestamp = int(time.time())
    safe_name = f"{upload_id}_{slot_name}_{timestamp}{ext}"
    file_path = IMAGE_DIR / safe_name

    content = await file.read()
    file_path.write_bytes(content)

    return {
        "upload_id": upload_id,
        "slot_name": slot_name,
        "file_path": str(file_path),
        "filename": safe_name,
    }


# ────────────────────────── parse debug endpoint ──────────────────────────


@app.post("/parse")
async def parse_only(file: UploadFile = File(...)):
    """Upload a single .docx file and return only the parsed section map (no database save, no LLM calls)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    if not file.filename.lower().endswith(".docx"):
        raise HTTPException(
            status_code=400,
            detail="Only .docx files are supported. Received: " + file.filename,
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        section_map = parse_docx(file_bytes)
        return section_map
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Parsing error: {exc}")


# ────────────────────────── health check ──────────────────────────


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ────────────────────────── run with uvicorn ──────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
