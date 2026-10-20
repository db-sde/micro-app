"""Fsynced remote-success journal covers local DB/enqueue failure without republishing.

Keep this directory on a persistent disk. No credentials or original upload metadata
are journaled. The normal path saves WP references and outbox in one SQL transaction.
"""
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from catalog.service import lock, record_publication, enqueue_safe, safe_data
from db.models import Upload


def directory():
    return Path(os.getenv("CATALOG_RECOVERY_DIR", str(Path(__file__).resolve().parents[1] / "catalog-recovery")))


def write(upload_id, page_type, payload, result, site, *, catalog_slug=None):
    root = directory()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    operation_id = str(uuid4())
    record = dict(upload_id=upload_id, page_type=page_type, payload=safe_data(payload, page_type),
                  result={k: result.get(k) for k in ("id", "link", "status", "linked_university", "linked_course")},
                  site=site, operation_id=operation_id, published_at=time.time(), catalog_slug=catalog_slug)
    path = root / f"{operation_id}.json"
    temp = root / f"{operation_id}.tmp"
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(record, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    descriptor = os.open(root, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return path, record


def apply(db, record):
    upload = db.get(Upload, record["upload_id"])
    if not upload:
        # Preserve deleted-upload work by using a detached minimal reference;
        # catalog_publications has no FK to uploads intentionally.
        upload = Upload(id=record["upload_id"], filename="recovered", page_type=record["page_type"])
    from catalog.models import CatalogPublication
    existing = db.get(CatalogPublication, upload.id)
    if existing and existing.published_at > record["published_at"]:
        return existing
    result = record["result"]
    publication = record_publication(db, upload, record["payload"], result, record["site"], record["operation_id"], record["published_at"])
    if record.get("catalog_slug"):
        from catalog.models import CatalogPost
        from catalog.config import SyncError
        post = db.get(CatalogPost, publication.post_id)
        if post.entity_slug and post.entity_slug != record["catalog_slug"]:
            raise SyncError("An applied catalog slug cannot change automatically.")
        post.catalog_slug = record["catalog_slug"]
    if db.get(Upload, upload.id):
        payload = json.loads(upload.payload or "{}")
        payload.setdefault("_meta", {}).update(wp_post_id=result["id"], wp_post_url=result["link"],
            wp_status=result["status"], wp_site=record["site"], linked_university=result.get("linked_university"), linked_course=result.get("linked_course"))
        upload.payload = json.dumps(payload, ensure_ascii=False)
        upload.status = "published" if result["status"] == "publish" else "draft_published"
    return publication


def recover(factory):
    root = directory()
    if not root.exists():
        return
    records = [(path, json.loads(path.read_text())) for path in root.glob("*.json")]
    for path, record in sorted(records, key=lambda item: item[1]["published_at"]):
        with factory() as db:
            lock(db)
            publication = apply(db, record)
            if publication.operation_id == record["operation_id"]:
                enqueue_safe(db, publication)
            db.commit()
        path.unlink(missing_ok=True)
