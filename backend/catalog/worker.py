from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import threading
import time
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import defer

from catalog.config import settings, SyncError
from catalog.models import CatalogLock, CatalogPost, CatalogEvent
from catalog.service import ACTIVE, lock, bind_site, dependencies, latest_publication

logger = logging.getLogger(__name__)
LEASE_SECONDS = 90


def signed_headers(secret, method, path, body=b"", *, now=None):
    timestamp = str(int(time.time() if now is None else now))
    message = f"{timestamp}.{method.upper()}.{path}.".encode("utf-8") + body
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {"Content-Type": "application/json", "X-Catalog-Timestamp": timestamp,
            "X-Catalog-Signature": "sha256=" + signature}


def delay(attempts):
    return min(3600, 2 ** min(attempts, 11)) * random.uniform(0.75, 1.25)


def claim(factory, config, now):
    with factory() as db:
        binding = lock(db)
        bind_site(db, config)
        if binding.sender_until > now:
            db.rollback()
            return None
        jobs = db.scalars(select(CatalogEvent).options(defer(CatalogEvent.body)).where(CatalogEvent.status.in_(ACTIVE), CatalogEvent.next_attempt <= now,
                         CatalogEvent.lease_until <= now).order_by(CatalogEvent.post_id, CatalogEvent.version)).all()
        for job in jobs:
            older = db.scalar(select(CatalogEvent.event_id).where(CatalogEvent.post_id == job.post_id,
                              CatalogEvent.version < job.version, CatalogEvent.status.in_(ACTIVE)).limit(1))
            if older:
                continue
            post = db.get(CatalogPost, job.post_id)
            publication = latest_publication(db, post)
            if publication.wp_status != "publish":
                job.status = "failed"
                job.last_error = "WordPress is no longer published. Catalog withdrawal is unsupported; operator action required."
                continue
            error, permanent = dependencies(db, job)
            if error:
                job.last_error = error
                job.status = "failed" if permanent else "queued"
                job.next_attempt = now + 30
                continue
            token = str(uuid4())
            binding.sender_token, binding.sender_until = token, now + LEASE_SECONDS
            job.lease_token, job.lease_until = token, now + LEASE_SECONDS
            job.status, job.last_error = "syncing", None
            job.attempts += 1
            data = dict(event_id=job.event_id, body=bytes(job.body), delivered=bool(job.delivered), token=token)
            db.commit()
            return data
        db.commit()
        return None


HTTP_ERRORS = {
    401: "Catalog authentication failed. Check the shared secret, signature configuration and synchronized machine clocks.",
    409: "Catalog event/version conflict. Review source mappings and receiver events before creating a corrected new version.",
    413: "Catalog payload exceeds receiver size limit (2 MiB). Correct content and create a new version.",
    422: "Receiver rejected schema or source host. Check canonical URL, relationships and reviewed content before a new version.",
}


def receive(factory, claimed, response, now):
    with factory() as db:
        lock(db)
        job = db.get(CatalogEvent, claimed["event_id"])
        binding = db.get(CatalogLock, 1)
        if job.lease_token != claimed["token"] or binding.sender_token != claimed["token"]:
            return  # Expired sender must never overwrite a newer lease's result.
        job.lease_token, job.lease_until = None, 0
        binding.sender_token, binding.sender_until = None, 0
        job.next_attempt = now + delay(job.attempts)
        if response is None:
            job.status, job.last_error = "queued", "Chatbot unavailable. Stored event will retry automatically."
        elif response.status_code == 404 and claimed["delivered"]:
            job.delivered, job.status = 0, "queued"
            job.last_error = "Receiver receipt missing. Resending the same stored event."
        elif response.status_code in (200, 202):
            try:
                result = response.json()
                state = result["status"]
                if result.get("event_id") != job.event_id or state not in ("queued", "applied", "ignored", "failed"):
                    raise ValueError
                # Receiver errors/warnings are a safe contract. Bound their size and
                # redact secrets defensively; never reflect HTTP bodies/exceptions.
                config = settings()
                def safe(value):
                    return str(value).replace(config.secret, "[redacted]")[:1000]
                job.delivered = 1
                job.last_error = safe(result["last_error"]) if result.get("last_error") else None
                warnings = result.get("warnings") or []
                if not isinstance(warnings, list):
                    raise ValueError
                job.warnings = json.dumps([safe(w) for w in warnings[:20]])
                if state == "applied":
                    post = db.get(CatalogPost, job.post_id)
                    slug = result.get("entity_slug")
                    import re
                    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) or len(slug) > 80:
                        raise ValueError
                    post.applied_version = max(post.applied_version, job.version)
                    post.entity_slug, job.status = slug, "synced"
                elif state == "ignored":
                    job.status = "superseded"
                    post = db.get(CatalogPost, job.post_id)
                    if post.applied_version < post.version:
                        job.last_error = "Receiver ignored this version. Latest local version is not confirmed applied; review receiver source/version state."
                elif state == "failed":
                    job.status = "failed"
                    job.last_error = job.last_error or "Receiver import failed. Correct the snapshot and create a new version."
                else:
                    job.status = "syncing"
                    job.next_attempt = now + min(60, delay(job.attempts))
            except (ValueError, KeyError, TypeError):
                job.status, job.last_error = "queued", "Invalid catalog receipt response. Stored event will retry."
        elif response.status_code == 429 or response.status_code >= 500:
            job.status, job.last_error = "queued", f"Chatbot HTTP {response.status_code}; stored event will retry."
        else:
            job.status = "failed"
            job.last_error = HTTP_ERRORS.get(response.status_code, "Unexpected catalog HTTP response/redirect. Check server configuration before retrying.")
        db.commit()


def tick(factory, *, client=None, now=None):
    try:
        config = settings()
        if not config:
            return False
        current = time.time() if now is None else now
        claimed = claim(factory, config, current)
        if not claimed:
            return False
        path = "/webhook/catalog"
        method, body = "POST", claimed["body"]
        if claimed["delivered"]:
            method, path, body = "GET", f"{path}/{claimed['event_id']}", b""
        headers = signed_headers(config.secret, method, path, body, now=now)
        response = None
        try:
            if client is not None:
                response = client.request(method, config.base_url + path, content=body, headers=headers, follow_redirects=False)
            else:
                with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False) as sender:
                    response = sender.request(method, config.base_url + path, content=body, headers=headers)
        except httpx.HTTPError:
            pass
        receive(factory, claimed, response, time.time() if now is None else now)
        return True
    except SyncError:
        # UI renders the fixed configuration error. Never log settings or requests.
        return False


class Worker:
    def __init__(self, factory):
        self.factory = factory
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="catalog-sender", daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        from catalog.recovery import recover
        while not self.stop.is_set():
            try:
                recover(self.factory)
            except Exception:
                logger.error("CATALOG_RECOVERY_FAILURE: retained journal requires storage recovery")
            try:
                tick(self.factory)
            except Exception:
                logger.error("CATALOG_WORKER_FAILURE: retrying durable work")
            self.stop.wait(2)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=25)
