import json
import re
import time
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from catalog.config import SyncError, settings
from catalog.models import CatalogPost, CatalogPublication, CatalogEvent, CatalogBackfill
from catalog.service import (lock, status_for, latest_publication, record_publication, enqueue,
                             backfill_preview, start_backfill, backfill_progress, PROTECTED, ACTIVE, wp_id)
from db.database import get_db
from db.models import Upload
from pipeline import wordpress_client
from acf.fields import ACF_FIELDS

router = APIRouter(prefix="/catalog", tags=["catalog sync"])


class PostSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_slug: str | None = Field(default=None, max_length=80)
    clear_fields: list[str] = Field(default_factory=list, max_length=100)
    removals_approved: bool = False


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wp_post_id: str | None = None
    reviewed: bool = False


def get_upload(db, upload_id):
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "Upload not found.")
    return upload


def fail(exc):
    raise HTTPException(400, str(exc)) from None


@router.get("/uploads/{upload_id}")
def upload_status(upload_id: int, db: Session = Depends(get_db)):
    return status_for(db, get_upload(db, upload_id))


@router.put("/uploads/{upload_id}/settings")
def save_settings(upload_id: int, body: PostSettings, db: Session = Depends(get_db)):
    upload = get_upload(db, upload_id)
    lock(db)
    publication = db.get(CatalogPublication, upload.id)
    if not publication:
        raise HTTPException(400, "Publish or reconcile the existing WordPress post before configuring its catalog mapping.")
    post = db.get(CatalogPost, publication.post_id)
    slug = body.catalog_slug or None
    if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
        raise HTTPException(400, "Use a reviewed catalog slug containing lowercase letters, numbers and hyphens.")
    if post.entity_slug and slug and post.entity_slug != slug:
        raise HTTPException(400, "An applied catalog mapping cannot change slug automatically. Review it with the chatbot operator.")
    allowed = {f["key"] for f in ACF_FIELDS.get(post.page_type, []) if f["type"] not in ("image", "file", "relation")} - PROTECTED
    if set(body.clear_fields) - allowed:
        raise HTTPException(400, "Only supported content fields can be explicitly cleared; identity and relationships cannot be cleared.")
    if body.clear_fields and not body.removals_approved:
        raise HTTPException(400, "Explicitly approve removals before saving clear_fields.")
    post.catalog_slug = slug
    post.clear_fields = json.dumps(sorted(set(body.clear_fields)))
    db.commit()
    return status_for(db, upload)


@router.post("/uploads/{upload_id}/retry")
def retry(upload_id: int, db: Session = Depends(get_db)):
    upload = get_upload(db, upload_id)
    lock(db)
    publication = db.get(CatalogPublication, upload.id)
    if not publication:
        raise HTTPException(400, "Reconcile the successful WordPress publication first; do not republish just to retry catalog sync.")
    publication = latest_publication(db, db.get(CatalogPost, publication.post_id))
    job = db.get(CatalogEvent, publication.event_id) if publication.event_id else None
    try:
        if job and job.status in ACTIVE:
            if job.lease_until > time.time():
                raise SyncError("This event is currently syncing; wait for its active lease.")
            job.next_attempt = 0
        elif job and job.status == "superseded":
            raise SyncError("Superseded snapshots cannot be forced over newer receiver versions. Review the latest mapping with the chatbot operator.")
        elif job and job.status == "synced":
            raise SyncError("This snapshot is already synced. Publish updated content to create a new version.")
        else:
            if not settings():
                raise SyncError("Configure the chatbot integration first.")
            # Failed immutable events remain untouched; correction uses a new event/version.
            enqueue(db, publication, force=bool(job))
        db.commit()
    except SyncError as exc:
        fail(exc)
    return status_for(db, upload)


@router.post("/uploads/{upload_id}/reconcile")
def reconcile(upload_id: int, body: ReconcileRequest, db: Session = Depends(get_db)):
    upload = get_upload(db, upload_id)
    if not body.reviewed:
        raise HTTPException(400, "Confirm that the original reviewed upload content matches the published WordPress page before reconciliation.")
    payload = json.loads(upload.payload or "{}")
    meta = payload.get("_meta") or {}
    source_id = wp_id(body.wp_post_id or meta.get("wp_post_id"))
    if not source_id:
        raise HTTPException(400, "Enter the existing WordPress post ID. This action reads that post and never creates one.")
    if meta.get("wp_post_id") and str(meta["wp_post_id"]) != source_id:
        raise HTTPException(400, "This upload is already linked to another WordPress post.")
    try:
        result = wordpress_client.read_catalog_references(upload.page_type, source_id)
    except Exception:
        raise HTTPException(502, "Could not read WordPress references. Check server credentials and the existing post ID.") from None
    lock(db)
    existing = db.get(CatalogPublication, upload.id)
    if existing and existing.reviewed:
        # Reconciliation of metadata must never silently sync un-published editor changes.
        payload = json.loads(existing.snapshot)
    publication = record_publication(db, upload, payload, result, wordpress_client._site_url(), str(uuid4()), time.time())
    stored = json.loads(upload.payload or "{}")
    stored.setdefault("_meta", {}).update(wp_post_id=result["id"], wp_post_url=result["link"], wp_status=result["status"],
        wp_site=wordpress_client._site_url(), linked_university=result.get("linked_university"), linked_course=result.get("linked_course"))
    upload.payload = json.dumps(stored, ensure_ascii=False)
    upload.status = "published" if result["status"] == "publish" else "draft_published"
    publication.error = None
    # Operator can now set a reviewed adoption slug BEFORE any delivery.
    db.commit()
    return status_for(db, upload)


@router.post("/backfills/preview")
def preview(db: Session = Depends(get_db)):
    lock(db)
    try:
        result = backfill_preview(db)
        db.commit()
        return result
    except SyncError as exc:
        fail(exc)


@router.post("/backfills")
def start(db: Session = Depends(get_db)):
    lock(db)
    try:
        run = start_backfill(db)
        db.commit()
        return backfill_progress(db, run)
    except SyncError as exc:
        fail(exc)


@router.get("/backfills")
def runs(db: Session = Depends(get_db)):
    return [backfill_progress(db, run) for run in db.scalars(select(CatalogBackfill).order_by(CatalogBackfill.created_at.desc()).limit(20))]


@router.get("/backfills/{run_id}")
def progress(run_id: str, db: Session = Depends(get_db)):
    run = db.get(CatalogBackfill, run_id)
    if not run:
        raise HTTPException(404, "Backfill not found.")
    return backfill_progress(db, run)
