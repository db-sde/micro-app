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
POST   /upload-image         Upload an image, store its URL on an ACF field
POST   /publish/{upload_id}  Publish an upload's ACF payload to WordPress
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
from fastapi.staticfiles import StaticFiles
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
from pipeline.blog_pipeline import generate_blog_summary
from pipeline import wordpress_client
from acf.fields import get_image_field_keys

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

# Allow all origins for parsing API endpoints
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ────────────────────────── directories ──────────────────────────

UPLOAD_DIR = Path(__file__).resolve().parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
IMAGE_DIR = UPLOAD_DIR / "images"
IMAGE_DIR.mkdir(exist_ok=True)

# Serve locally-stored images over HTTP — used as a fallback URL source
# when WordPress media upload is not configured or fails.
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

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


class PatchPayloadRequest(BaseModel):
    payload: dict
    page_type: str | None = None  # optional re-classification


class PublishRequest(BaseModel):
    status: str = "draft"   # draft | publish | pending
    title: str | None = None


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


@app.post("/upload-blog")
async def upload_blog_docx(
    file: UploadFile = File(...),
    page_type: str = Form(default="blog"),
):
    """Upload a .docx file for a blog/category page and get a 4-5 point summary."""
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
        # Extract raw text from the document
        parsed_data = parse_docx(file_bytes)
        raw_text = parsed_data.get("raw_text", "")
        
        if not raw_text.strip():
            raise ValueError("No text could be extracted from the document.")
            
        # Generate summary + SEO fields via Claude
        result_json = generate_blog_summary(raw_text, page_type)
        
        # Parse the structured result
        try:
            result_data = json.loads(result_json)
        except json.JSONDecodeError:
            result_data = {"complete_page_summary": result_json, "seo_title": "", "meta_description": ""}
        
        return {
            "filename": file.filename,
            "page_type": page_type,
            "payload": result_data,
        }
    except Exception as exc:
        logger.error("Blog pipeline failed: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"Blog pipeline error: {exc}")


@app.get("/upload/{upload_id}")
async def get_upload(upload_id: int, db: Session = Depends(get_db)):
    """Get the full upload data including payload and mappings."""
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    existing_payload: dict[str, Any] = {}
    if upload.payload:
        try:
            existing_payload = json.loads(upload.payload)
        except json.JSONDecodeError:
            pass

    validation = validate_payload(existing_payload, upload.page_type or "university")

    mappings = (
        db.query(FieldMapping)
        .filter(FieldMapping.upload_id == upload_id)
        .all()
    )

    return {
        "id": upload.id,
        "filename": upload.filename,
        "page_type": upload.page_type,
        "status": upload.status,
        "score": upload.score,
        "payload": existing_payload,
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


@app.patch("/payload/{upload_id}")
async def patch_payload(
    upload_id: int,
    body: PatchPayloadRequest,
    db: Session = Depends(get_db),
):
    """Overwrite the ACF payload for an upload with manually-edited content.

    Optionally re-classifies the page type if ``page_type`` is supplied.
    Re-runs validation and updates the quality score.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    # Validate page_type if provided
    allowed_types = ("university", "course", "specialization")
    if body.page_type and body.page_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid page_type: {body.page_type!r}. Must be one of {allowed_types}.",
        )

    # Apply page type reclassification
    if body.page_type:
        upload.page_type = body.page_type

    effective_page_type = upload.page_type or "university"

    # Persist the edited payload
    try:
        upload.payload = json.dumps(body.payload, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload JSON: {exc}")

    # Re-validate with the (possibly new) page type
    validation = validate_payload(body.payload, effective_page_type)
    upload.score = validation["summary"]["quality_score"]
    upload.status = "confirmed"

    db.commit()
    db.refresh(upload)

    # Return refreshed field mappings
    mappings = (
        db.query(FieldMapping)
        .filter(FieldMapping.upload_id == upload_id)
        .all()
    )

    return {
        "upload_id": upload.id,
        "page_type": upload.page_type,
        "status": upload.status,
        "payload": body.payload,
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
    """Check the progress of a bulk processing job.

    Each per-file result always returns the latest ``quality_score`` and
    ``acf_extracted`` / ``acf_total`` from the Upload table so that edits
    made via the JSON editor are reflected when the caller re-fetches.
    """
    job = db.query(BulkJob).filter(BulkJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Bulk job not found.")

    per_file_results: list[dict] = []
    if job.results:
        try:
            per_file_results = json.loads(job.results)
        except json.JSONDecodeError:
            per_file_results = []

    # Refresh quality_score + acf counts from the live Upload record so that
    # any JSON edits made via the validation screen are reflected here.
    for result in per_file_results:
        uid = result.get("upload_id")
        if not uid:
            continue
        try:
            upload = db.query(Upload).filter(Upload.id == uid).first()
            if upload:
                result["quality_score"] = upload.score or 0.0
                # Re-compute acf counts from latest payload validation
                if upload.payload:
                    try:
                        payload_data = json.loads(upload.payload)
                        validation = validate_payload(payload_data, upload.page_type or "university")
                        v_summary = validation["summary"]
                        result["acf_extracted"] = v_summary.get("mapped", 0) + v_summary.get("thin", 0)
                        result["acf_total"] = v_summary.get("total_required", 0)
                    except Exception:
                        pass
        except Exception:
            pass

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


_IMAGE_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}


@app.post("/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    upload_id: int = Form(...),
    slot_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Upload an image for a given ACF image field ("slot") on an upload.

    The image is pushed to the WordPress media library and the resulting
    media URL is written directly into the upload's ACF payload under
    ``slot_name`` — so it is present in the JSON returned by ``/download``
    and ``/upload/{id}`` without any further action.

    If WordPress is configured but the upload call fails, this raises a 502
    rather than silently falling back to local disk: a URL served by this
    backend's own machine is very likely unreachable from WordPress (or
    anywhere else) once published, so a loud, retryable error is safer than
    quietly writing a dead URL into the field. Local-disk fallback only
    applies when WordPress isn't configured at all (pure local dev/testing),
    and the response carries an explicit ``warning`` in that case.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided.")

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _IMAGE_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported image format: {ext}. Allowed: {', '.join(_IMAGE_CONTENT_TYPES)}",
        )

    page_type = upload.page_type or "university"
    valid_slots = get_image_field_keys(page_type)
    if slot_name not in valid_slots:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid slot_name {slot_name!r} for page_type {page_type!r}. "
                f"Must be one of: {', '.join(sorted(valid_slots))}"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    mime_type = _IMAGE_CONTENT_TYPES[ext]
    timestamp = int(time.time())
    safe_name = f"{upload_id}_{slot_name}_{timestamp}{ext}"

    image_url: str
    wp_media_id: int | None = None
    image_source: str
    warning: str | None = None

    if wordpress_client.is_configured():
        # WordPress is the intended destination for this URL. If the upload
        # fails here, do NOT fall back to a local URL — a file served by
        # this backend's own machine is generally unreachable from
        # WordPress (or anyone else) once published, so surfacing a clear,
        # retryable error is safer than silently writing in a dead link.
        try:
            media = wordpress_client.upload_media(content, safe_name, mime_type)
            image_url = media["source_url"]
            wp_media_id = media["id"]
            image_source = "wordpress"
        except Exception as exc:
            logger.error(
                "WordPress media upload failed for upload %d slot %r: %s",
                upload_id, slot_name, exc,
            )
            raise HTTPException(
                status_code=502,
                detail=(
                    f"WordPress media upload failed: {exc}. Check that the site is "
                    f"reachable from this server, the Application Password is valid "
                    f"and has upload permission, and the media REST route isn't "
                    f"blocked by a security plugin/WAF. Not falling back to local "
                    f"storage, since that URL would not be reachable from WordPress."
                ),
            )
    else:
        # WordPress isn't configured at all — pure local dev/testing path.
        # This URL is only reachable from wherever THIS backend is running;
        # it will not work once the JSON is published elsewhere unless
        # BACKEND_PUBLIC_URL is set to a publicly reachable address.
        file_path = IMAGE_DIR / safe_name
        file_path.write_bytes(content)
        backend_base = os.getenv("BACKEND_PUBLIC_URL", "http://localhost:8000").rstrip("/")
        image_url = f"{backend_base}/uploads/images/{safe_name}"
        image_source = "local"
        warning = (
            f"WordPress is not configured on this server — this image was stored "
            f"locally at {image_url}, which is only reachable from wherever this "
            f"backend is running. Set WORDPRESS_SITE_URL / WORDPRESS_APP_USER / "
            f"WORDPRESS_APP_PASSWORD to get a URL that works once published."
        )

    # ── Persist the URL directly into the ACF payload ──
    # Re-fetch (and lock, on Postgres) the row NOW rather than reusing the
    # `upload` object loaded at the top of this function. Several image
    # slots are typically uploaded back-to-back for the same upload_id;
    # the WordPress call above can take a while, so a stale in-memory
    # payload here would silently clobber whichever other slot's write
    # landed in between — each request "succeeds" individually but only
    # the last commit's slot survives. with_for_update() serializes
    # concurrent requests for the same upload_id on Postgres; it's a
    # harmless no-op on the SQLite dev fallback.
    upload = (
        db.query(Upload)
        .filter(Upload.id == upload_id)
        .with_for_update()
        .first()
    )
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    existing_payload: dict[str, Any] = {}
    if upload.payload:
        try:
            existing_payload = json.loads(upload.payload)
        except json.JSONDecodeError:
            existing_payload = {}

    existing_payload[slot_name] = image_url
    upload.payload = json.dumps(existing_payload, ensure_ascii=False)

    # Upsert the field mapping row so the UI/validation reflects the new value
    fm = (
        db.query(FieldMapping)
        .filter(FieldMapping.upload_id == upload_id, FieldMapping.field_key == slot_name)
        .first()
    )
    mapping_source = "WORDPRESS" if image_source == "wordpress" else "LOCAL_UPLOAD"
    if fm:
        fm.value = image_url
        fm.heading_in_doc = "[image upload]"
        fm.confidence = 1.0
        fm.status = "mapped"
        fm.source = mapping_source
        fm.is_confirmed = True
    else:
        fm = FieldMapping(
            upload_id=upload_id,
            field_key=slot_name,
            heading_in_doc="[image upload]",
            value=image_url,
            confidence=1.0,
            status="mapped",
            source=mapping_source,
            is_confirmed=True,
        )
        db.add(fm)

    # Re-validate so the quality score reflects the newly-filled image field
    validation = validate_payload(existing_payload, page_type)
    upload.score = validation["summary"]["quality_score"]

    db.commit()
    db.refresh(upload)

    return {
        "upload_id": upload_id,
        "slot_name": slot_name,
        "url": image_url,
        "wp_media_id": wp_media_id,
        "source": image_source,
        "warning": warning,
        "payload": existing_payload,
        "validation": validation,
    }


@app.post("/publish/{upload_id}")
async def publish_to_wordpress(
    upload_id: int,
    body: PublishRequest = PublishRequest(),
    db: Session = Depends(get_db),
):
    """Publish an upload's ACF JSON payload directly to WordPress.

    Creates a post of the CPT matching the upload's page_type (see
    ``wordpress_client.get_post_type``) with all ACF fields — including any
    image URLs set via ``/upload-image`` — attached under the ``acf`` key.

    Defaults to ``status="draft"``. If this upload was already published
    once (tracked in ``payload._meta.wp_post_id``), re-publishing updates
    that same post instead of creating a duplicate.
    """
    upload = db.query(Upload).filter(Upload.id == upload_id).first()
    if not upload:
        raise HTTPException(status_code=404, detail="Upload not found.")

    if not upload.payload:
        raise HTTPException(
            status_code=400,
            detail="No payload available for this upload. Process the document first.",
        )

    try:
        payload_data = json.loads(upload.payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Stored payload is corrupted JSON.")

    page_type = upload.page_type or "university"
    if page_type not in ("university", "course", "specialization"):
        raise HTTPException(
            status_code=400,
            detail=f"Publishing is only supported for university/course/specialization pages, got {page_type!r}.",
        )

    if not wordpress_client.is_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "WordPress is not configured on the server "
                "(missing WORDPRESS_SITE_URL / WORDPRESS_APP_USER / WORDPRESS_APP_PASSWORD)."
            ),
        )

    existing_post_id = (payload_data.get("_meta") or {}).get("wp_post_id")

    try:
        result = wordpress_client.publish_payload(
            payload_data,
            page_type,
            status=body.status,
            post_id=existing_post_id,
            title=body.title,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("WordPress publish failed for upload %d: %s", upload_id, exc)
        raise HTTPException(status_code=502, detail=f"WordPress publish failed: {exc}")

    # Track the WP post reference in the payload so re-publishing updates it
    payload_data.setdefault("_meta", {})
    payload_data["_meta"]["wp_post_id"] = result["id"]
    payload_data["_meta"]["wp_post_url"] = result["link"]
    payload_data["_meta"]["wp_status"] = result["status"]
    upload.payload = json.dumps(payload_data, ensure_ascii=False)
    upload.status = "published" if result["status"] == "publish" else "draft_published"
    db.commit()
    db.refresh(upload)

    return {
        "upload_id": upload_id,
        "wp_post_id": result["id"],
        "wp_post_url": result["link"],
        "wp_edit_link": result["edit_link"],
        "wp_status": result["status"],
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
