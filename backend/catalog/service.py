from __future__ import annotations

import json
import re
import time
from uuid import uuid4
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from acf.fields import ACF_FIELDS, V2_PUBLISHED_FIELDS
from catalog.config import SyncError, settings
from catalog.models import CatalogLock, CatalogPost, CatalogPublication, CatalogEvent, CatalogBackfill
from db.models import Upload

TYPES = ("university", "course", "specialization")
ACTIVE = ("queued", "syncing")
PROTECTED = {"name", "full_name", "program_name", "spec_name", "university_name", "university_full_name", "course_name", "specialization_name", "slug", "catalog_slug", "id", "source_id", "linked_university", "linked_course", "university_id", "course_id", "university_source_id", "course_source_id"}


def migrate(engine):
    """Additive migration 0001: new tables only; safe with existing create_all startup."""
    from db.database import Base
    Base.metadata.create_all(engine, tables=[m.__table__ for m in (
        CatalogLock, CatalogPost, CatalogPublication, CatalogEvent, CatalogBackfill
    )])
    with engine.begin() as connection:
        insert = sqlite_insert if engine.dialect.name == "sqlite" else pg_insert
        connection.execute(insert(CatalogLock).values(id=1, revision=0, sender_until=0).on_conflict_do_nothing())


def lock(db):
    # UPDATE takes a row lock on PostgreSQL and a write lock on SQLite. All
    # writers take this before reading counters/claiming jobs, including first insert.
    db.execute(update(CatalogLock).where(CatalogLock.id == 1).values(revision=CatalogLock.revision + 1))
    return db.get(CatalogLock, 1, populate_existing=True)


def bind_site(db, config):
    binding = db.get(CatalogLock, 1)
    if binding.site and (binding.site != config.site or binding.destination != config.base_url):
        # The binding protects version history already sent to one chatbot
        # for one WordPress site. If nothing has ever been queued there is no
        # history to protect: the idle sender binds on every tick, so a
        # briefly mistyped CHATBOT_BASE_URL used to lock the parser to the
        # wrong origin permanently. Rebind in that case; refuse once real
        # events exist.
        if db.scalar(select(CatalogEvent.event_id).limit(1)) is not None:
            raise SyncError("Catalog is bound to another WordPress site/chatbot origin. Restore configuration; do not combine sites.")
    binding.site, binding.destination = config.site, config.base_url


def wp_id(value):
    if isinstance(value, list):
        if len(value) != 1:
            return None
        value = value[0]
    if isinstance(value, bool) or value is None or not re.fullmatch(r"[1-9][0-9]{0,18}", str(value)):
        return None
    return str(value)


def post_for(db, site, page_type, source_id):
    return db.scalar(select(CatalogPost).where(CatalogPost.site == site, CatalogPost.page_type == page_type, CatalogPost.wp_post_id == source_id))


def safe_data(payload, page_type):
    # Whitelist original ACF keys; never include _meta, routing, credentials or binary media.
    # Includes the live WordPress fields only the v2 parser fills (partner banks,
    # syllabus intro, exam cards...), so the chatbot can answer from them too.
    fields = [*ACF_FIELDS.get(page_type, []), *V2_PUBLISHED_FIELDS.get(page_type, [])]
    keys = {f["key"] for f in fields if f["type"] not in ("image", "file", "post_object", "relationship", "relation")}
    keys -= PROTECTED & {"linked_university", "linked_course"}
    return {k: v for k, v in payload.items() if k in keys and k not in ("category_page", "hero_image", "brochure")}


def record_publication(db, upload, payload, result, site, operation_id, published_at):
    source_id = wp_id(result.get("id"))
    if not source_id:
        raise SyncError("WordPress did not return a valid post ID. Reconcile the successful remote operation before publishing again.")
    post = post_for(db, site, upload.page_type, source_id)
    if not post:
        post = CatalogPost(site=site, page_type=upload.page_type, wp_post_id=source_id)
        db.add(post)
        db.flush()
    publication = db.get(CatalogPublication, upload.id)
    if publication and publication.operation_id == operation_id:
        return publication
    values = dict(post_id=post.id, operation_id=operation_id, published_at=published_at,
                  wp_status=result["status"], source_url=result.get("link"), reviewed=1,
                  university_id=wp_id(result.get("linked_university")),
                  course_id=wp_id(result.get("linked_course")),
                  snapshot=json.dumps(safe_data(payload, upload.page_type), ensure_ascii=False),
                  event_id=None, error=None)
    if not publication:
        publication = CatalogPublication(upload_id=upload.id, **values)
        db.add(publication)
    else:
        for key, value in values.items():
            setattr(publication, key, value)
    db.flush()
    return publication


def validate_snapshot(db, post, publication, config):
    if not publication.reviewed:
        raise SyncError("Review this legacy upload against its published WordPress page and reconcile references before backfill.")
    if post.site != config.site:
        raise SyncError("WordPress site differs from configured catalog source.")
    url = urlsplit(publication.source_url or "")
    if url.scheme != "https" or not url.hostname or url.hostname.lower() not in config.hosts or url.username or url.password or url.query or url.fragment:
        raise SyncError("Resolve a public HTTPS canonical WordPress URL on CHATBOT_CATALOG_SOURCE_HOSTS, without credentials, query or fragment.")
    try:
        if url.port not in (None, 443):
            raise ValueError
    except ValueError:
        raise SyncError("Canonical WordPress URL must use the standard HTTPS port.") from None
    if len(publication.source_url) > 2048:
        raise SyncError("Canonical WordPress URL exceeds 2048 characters.")
    if post.page_type != "university" and not publication.university_id:
        raise SyncError("Resolve exactly one linked_university WordPress post ID, then reconcile this upload.")
    if post.page_type == "specialization":
        if not publication.course_id:
            raise SyncError("Resolve exactly one linked_course WordPress post ID, then reconcile this upload.")
        course = post_for(db, post.site, "course", publication.course_id)
        parent = latest_publication(db, course) if course else None
        if parent and not parent.university_id:
            raise SyncError(f"Linked course #{publication.course_id} has no university recorded (it was probably published before its university existed). Republish that course so it links to university #{publication.university_id}, then retry.")
        if parent and parent.university_id != publication.university_id:
            raise SyncError("Course and specialization belong to different universities. Correct WordPress relationships and reconcile.")


def latest_publication(db, post):
    return db.scalar(select(CatalogPublication).where(CatalogPublication.post_id == post.id).order_by(CatalogPublication.published_at.desc(), CatalogPublication.upload_id.desc()).limit(1))


def enqueue(db, publication, *, force=False):
    config = settings()
    if not config:
        return None
    post = db.get(CatalogPost, publication.post_id)
    if post.page_type not in TYPES or publication.wp_status != "publish":
        return None
    bind_site(db, config)
    if publication.event_id and not force:
        publication.error = None
        return db.get(CatalogEvent, publication.event_id)
    latest = latest_publication(db, post)
    if latest.upload_id != publication.upload_id:
        raise SyncError("A newer published snapshot exists for this post. Sync the latest publication.")
    validate_snapshot(db, post, publication, config)
    # The caller holds catalog_lock through commit: counters and exact bytes are atomic.
    event_id = str(uuid4())
    version = post.version + 1
    event = dict(schema_version=1, event_id=event_id, source="degreebaba-parser",
                 entity_type=post.page_type, source_id=post.wp_post_id, version=version,
                 publication_status="publish", source_url=publication.source_url,
                 data=json.loads(publication.snapshot), clear_fields=json.loads(post.clear_fields))
    if post.page_type != "university":
        event["university_source_id"] = publication.university_id
    if post.page_type == "specialization":
        event["course_source_id"] = publication.course_id
    if post.catalog_slug:
        event["catalog_slug"] = post.catalog_slug
    body = json.dumps(event, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(body) > 2 * 1024 * 1024:
        raise SyncError("Catalog event exceeds 2 MiB. Reduce reviewed page content before creating a new event.")
    post.version = version
    post.clear_fields = "[]"
    job = CatalogEvent(event_id=event_id, post_id=post.id, version=version, body=body,
                       university_id=publication.university_id if post.page_type != "university" else None,
                       course_id=publication.course_id if post.page_type == "specialization" else None)
    db.add(job)
    publication.event_id, publication.error = event_id, None
    db.flush()
    return job


def enqueue_safe(db, publication):
    try:
        return enqueue(db, publication)
    except (SyncError, ValueError, TypeError) as exc:
        # Validation messages are fixed safe strings; JSON errors must not echo content.
        publication.error = str(exc) if isinstance(exc, SyncError) else "Invalid reviewed JSON content; correct it and create a new version."
        return None


def dependencies(db, job):
    event = {key: value for key, value in (("university_source_id", job.university_id),
             ("course_source_id", job.course_id)) if value}
    post = db.get(CatalogPost, job.post_id)
    for kind, key in (("university", "university_source_id"), ("course", "course_source_id")):
        if key not in event:
            continue
        parent = post_for(db, post.site, kind, event[key])
        if not parent:
            return f"Missing {kind} WordPress post #{event[key]}. Import its reviewed original document, link the existing post and sync it first.", False
        publication = latest_publication(db, parent)
        if kind == "course" and publication and publication.university_id != event["university_source_id"]:
            return "Course and specialization university IDs mismatch. Correct relationships and create a new version.", True
        parent_job = db.get(CatalogEvent, publication.event_id) if publication and publication.event_id else None
        if not publication or publication.wp_status != "publish" or publication.error or not parent_job or parent_job.status != "synced" or parent.applied_version < parent.version or parent.applied_version == 0:
            return f"Waiting for published {kind} WordPress post #{event[key]} to apply. Sync the parent first.", False
    return None, False


def status_for(db, upload):
    publication = db.get(CatalogPublication, upload.id)
    try:
        configured = settings() is not None
    except SyncError as exc:
        return dict(status="failed", last_error=str(exc))
    if not configured:
        return dict(status="not configured", last_error=publication.error if publication else None)
    if not publication:
        # upload.status is "published" exactly when WordPress reported
        # status=publish (see recovery.apply). Checking it avoids parsing the
        # full payload JSON for every row of the history list.
        if upload.status == "published" and upload.page_type in TYPES:
            return dict(status="failed", last_error="Legacy publication needs review and WordPress reference reconciliation before backfill.")
        return dict(status="not eligible/draft", last_error="Published upserts only. Draft/private/deleted changes do not withdraw existing chatbot records.")
    post = db.get(CatalogPost, publication.post_id)
    latest = latest_publication(db, post)
    if latest.wp_status != "publish" or post.page_type not in TYPES:
        return dict(status="not eligible/draft", last_error="Published upserts only. Existing chatbot content is not withdrawn; operator action required.")
    job = db.get(CatalogEvent, latest.event_id) if latest.event_id else None
    return dict(status="failed" if latest.error else (job.status if job else "queued"),
                last_error=latest.error or (job.last_error if job else "Ready for reviewed backfill."),
                event_id=job.event_id if job else None, version=job.version if job else post.version,
                delivered=bool(job.delivered) if job else False,
                warnings=json.loads(job.warnings) if job else [], entity_slug=post.entity_slug,
                wp_post_id=post.wp_post_id, catalog_slug=post.catalog_slug or "",
                clear_fields=json.loads(post.clear_fields), post_id=post.id)


def seed_legacy(db, site):
    """No HTTP. Missing relationship metadata remains an explicit review error."""
    for upload in db.scalars(select(Upload).order_by(Upload.updated_at, Upload.id)):
        if db.get(CatalogPublication, upload.id):
            continue
        payload = json.loads(upload.payload or "{}")
        meta = payload.get("_meta") or {}
        if not wp_id(meta.get("wp_post_id")):
            continue
        if meta.get("wp_site") and meta["wp_site"] != site:
            continue
        publication = record_publication(db, upload, payload, dict(id=meta["wp_post_id"], link=meta.get("wp_post_url"),
            status=meta.get("wp_status", "unknown"), linked_university=meta.get("linked_university"), linked_course=meta.get("linked_course")),
            site, str(uuid4()), upload.updated_at.timestamp())
        publication.reviewed = 0
        publication.error = "Legacy snapshot needs review against WordPress and reference reconciliation before backfill."


def backfill_preview(db):
    config = settings()
    if not config:
        raise SyncError("Configure the chatbot integration before backfill.")
    seed_legacy(db, config.site)
    rows = []
    counts = {"ready": 0, "blocked": 0, "existing": 0, "ineligible": 0}
    posts = db.scalars(select(CatalogPost).where(CatalogPost.site == config.site)).all()
    posts.sort(key=lambda p: (TYPES.index(p.page_type) if p.page_type in TYPES else 3, p.id))
    for post in posts:
        publication = latest_publication(db, post)
        error = None
        state = "ready"
        if publication.wp_status != "publish" or post.page_type not in TYPES:
            state = "ineligible"
        else:
            try:
                bind_site(db, config)
                validate_snapshot(db, post, publication, config)
                if publication.event_id:
                    state = "existing"
                    existing_job = db.get(CatalogEvent, publication.event_id)
                    error = existing_job.last_error
                elif post.page_type != "university":
                    parents = [("university", publication.university_id)]
                    if post.page_type == "specialization":
                        parents.append(("course", publication.course_id))
                    for kind, source_id in parents:
                        parent = post_for(db, post.site, kind, source_id)
                        if not parent or latest_publication(db, parent).wp_status != "publish":
                            raise SyncError(f"Missing published {kind} post #{source_id}. Import/link and sync that parent first.")
            except SyncError as exc:
                error, state = str(exc), "blocked"
        counts[state] += 1
        rows.append(dict(post_id=post.id, upload_id=publication.upload_id, page_type=post.page_type,
                         wp_post_id=post.wp_post_id, state=state, error=error, catalog_slug=post.catalog_slug))
    # A known but blocked parent is just as actionable as a missing parent.
    by_identity = {(row["page_type"], row["wp_post_id"]): row for row in rows}
    for row in rows:
        if row["state"] != "ready" or row["page_type"] == "university":
            continue
        publication = db.get(CatalogPublication, row["upload_id"])
        parents = [("university", publication.university_id)]
        if row["page_type"] == "specialization":
            parents.append(("course", publication.course_id))
        for kind, source_id in parents:
            parent = by_identity.get((kind, source_id))
            if parent and parent["state"] in ("blocked", "ineligible"):
                row["state"] = "blocked"
                row["error"] = f"Review/reconcile published parent {kind} #{source_id} first."
                counts["ready"] -= 1
                counts["blocked"] += 1
                break
    return dict(counts=counts, posts=rows, coverage="Only locally saved publications/reviewed uploads are covered. WordPress may contain other pages; no site crawl has been performed.")


def start_backfill(db):
    preview = backfill_preview(db)
    items = []
    for row in preview["posts"]:
        if row["state"] in ("ready", "existing"):
            publication = db.get(CatalogPublication, row["upload_id"])
            job = enqueue(db, publication)
            items.append(dict(post_id=row["post_id"], event_id=job.event_id))
    run = CatalogBackfill(id=str(uuid4()), created_at=time.time(), items=json.dumps(items))
    db.add(run)
    return run


def backfill_progress(db, run):
    counts = {}
    items = []
    for item in json.loads(run.items):
        job = db.get(CatalogEvent, item["event_id"])
        state = job.status
        counts[state] = counts.get(state, 0) + 1
        items.append({**item, "status": state, "last_error": job.last_error})
    return dict(id=run.id, counts=counts, total=len(items), complete=all(i["status"] not in ACTIVE for i in items), items=items)
