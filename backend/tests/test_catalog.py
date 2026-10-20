"""Catalog contract checks: disposable SQLite, mocked WordPress and chatbot, no paid calls."""
import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from catalog import recovery, service, worker
from catalog.config import settings, SyncError
from catalog.models import CatalogPost, CatalogPublication, CatalogEvent, CatalogLock
from db.database import Base, get_db
from db.models import Upload
from main import app
from pipeline import wordpress_client

pytestmark = pytest.mark.allow_httpx
SECRET = "test-shared-secret-never-production-12345"


@pytest.fixture
def factory(tmp_path, monkeypatch):
    monkeypatch.setenv("WORDPRESS_SITE_URL", "https://degreebaba.com")
    monkeypatch.setenv("CHATBOT_BASE_URL", "https://chatbot.test")
    monkeypatch.setenv("CHATBOT_CATALOG_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("CHATBOT_CATALOG_SOURCE_HOSTS", "degreebaba.com,www.degreebaba.com")
    monkeypatch.setenv("CATALOG_RECOVERY_DIR", str(tmp_path / "recovery"))
    engine = create_engine(f"sqlite:///{tmp_path}/catalog.db", connect_args={"check_same_thread": False, "timeout": 30})
    Base.metadata.create_all(engine)
    service.migrate(engine)
    result = sessionmaker(bind=engine, expire_on_commit=False)
    yield result
    engine.dispose()


@pytest.fixture
def api(factory):
    def dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    yield TestClient(app)  # No startup/embedding calls.
    app.dependency_overrides.clear()


def add_upload(factory, kind="university", source_id=None, **payload):
    data = {"university_name": "विश्वविद्यालय", "about_content": "<p>Reviewed text ₹1,20,000</p>", **payload}
    if source_id:
        data["_meta"] = {"wp_post_id": source_id}
    with factory() as db:
        upload = Upload(filename="private-name.docx", page_type=kind, payload=json.dumps(data))
        db.add(upload)
        db.commit()
        return upload.id


def wp_result(source_id=101, status="publish", university=None, course=None):
    return dict(id=source_id, status=status, link=f"https://degreebaba.com/catalog/{source_id}/", edit_link="https://degreebaba.com/wp-admin/", warnings=[], taxonomy_warnings=[], relationship_warnings=[], linked_university=university, linked_course=course)


def publish(api, monkeypatch, upload_id, result=None):
    monkeypatch.setattr(wordpress_client, "is_configured", lambda: True)
    monkeypatch.setattr(wordpress_client, "publish_payload", lambda *args, **kwargs: result or wp_result())
    response = api.post(f"/publish/{upload_id}", json={"status": "publish"})
    assert response.status_code == 200, response.text
    return response.json()


def saved(factory, upload_id, source_id, kind="university", university=None, course=None, enqueue=True):
    with factory() as db:
        service.lock(db)
        upload = db.get(Upload, upload_id)
        publication = service.record_publication(db, upload, json.loads(upload.payload), wp_result(source_id, university=university, course=course), "https://degreebaba.com", str(uuid4()), __import__('time').time())
        job = service.enqueue(db, publication) if enqueue else None
        db.commit()
        return job.event_id if job else None


def jobs(factory):
    with factory() as db:
        return db.scalars(select(CatalogEvent).order_by(CatalogEvent.version)).all()


class Chatbot:
    def __init__(self, state="queued", code=202):
        self.calls = []
        self.state = state
        self.code = code

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if isinstance(self.state, Exception):
            raise self.state
        event_id = json.loads(kwargs["content"])["event_id"] if method == "POST" else url.rsplit("/", 1)[1]
        return httpx.Response(self.code, json=dict(event_id=event_id, status=self.state, entity_slug="reviewed-entity", warnings=[], last_error=None))


def test_publish_enqueues_original_utf8_and_references_atomically(factory, api, monkeypatch):
    rows = [{"question": "परीक्षा?", "answer": "Online"}, {"question": "Fees?", "answer": "₹1,20,000"}]
    upload_id = add_upload(factory, "course", faqs=rows, total_fee="₹1,20,000", linked_university=None, access_token="DO NOT SEND", hero_image="binary", _meta={"relationship_hints": {"linked_university": "friendly name"}})
    response = publish(api, monkeypatch, upload_id, wp_result(202, university=[101]))
    assert response["wp_status"] == "publish"
    assert response["catalog_sync"]["status"] == "queued"
    event = jobs(factory)[0]
    body = json.loads(event.body)
    assert body["source_id"] == "202" and body["university_source_id"] == "101"
    assert "course_source_id" not in body
    assert body["data"]["faqs"] == rows
    assert body["data"]["total_fee"] == "₹1,20,000"
    assert "₹".encode() in event.body and "परीक्षा".encode() in event.body
    assert not ({"_meta", "access_token", "hero_image", "linked_university"} & body["data"].keys())
    with factory() as db:
        meta = json.loads(db.get(Upload, upload_id).payload)["_meta"]
        assert meta["linked_university"] == [101]
        assert db.get(CatalogPublication, upload_id).event_id == event.event_id
    assert list(recovery.directory().glob("*.json")) == []


@pytest.mark.parametrize("kind,status", [("university", "draft"), ("course", "private"), ("blog", "publish"), ("category", "publish")])
def test_ineligible_never_enqueued(factory, api, monkeypatch, kind, status):
    upload_id = add_upload(factory, kind)
    response = publish(api, monkeypatch, upload_id, wp_result(status=status))
    assert response["wp_status"] == status
    assert jobs(factory) == []
    assert response["catalog_sync"]["status"] == "not eligible/draft"


@pytest.mark.parametrize("missing", ["CHATBOT_BASE_URL", "CHATBOT_CATALOG_WEBHOOK_SECRET"])
def test_disabled_preserves_wordpress(factory, api, monkeypatch, missing):
    monkeypatch.setenv(missing, "")
    upload_id = add_upload(factory)
    result = publish(api, monkeypatch, upload_id)
    assert result["catalog_sync"]["status"] == "not configured"
    assert jobs(factory) == []


def test_remote_failure_creates_no_outbox(factory, api, monkeypatch):
    upload_id = add_upload(factory)
    monkeypatch.setattr(wordpress_client, "is_configured", lambda: True)
    def fail(*args, **kwargs):
        raise ValueError("mock publication failed")
    monkeypatch.setattr(wordpress_client, "publish_payload", fail)
    assert api.post(f"/publish/{upload_id}").status_code == 400
    assert jobs(factory) == []


def test_downtime_keeps_wp_success_and_retries_same_event_after_restart(factory, api, monkeypatch):
    upload_id = add_upload(factory)
    assert publish(api, monkeypatch, upload_id)["wp_status"] == "publish"
    original = jobs(factory)[0]
    client = Chatbot(httpx.ConnectError("offline"))
    worker.tick(factory, client=client, now=1000)
    assert jobs(factory)[0].status == "queued"
    client.state = "queued"
    worker.tick(factory, client=client, now=5000)
    assert client.calls[0][2]["content"] == client.calls[1][2]["content"] == original.body
    assert client.calls[0][2]["headers"] != client.calls[1][2]["headers"]
    assert jobs(factory)[0].delivered == 1 and jobs(factory)[0].status == "syncing"
    # A new tick/session simulates a restarted process: poll GET with empty bytes.
    client.state, client.code = "applied", 200
    worker.tick(factory, client=client, now=6000)
    method, url, kwargs = client.calls[-1]
    assert method == "GET" and url.endswith(original.event_id) and kwargs["content"] == b""
    assert jobs(factory)[0].status == "synced"
    assert api.get(f"/catalog/uploads/{upload_id}").json()["entity_slug"] == "reviewed-entity"


def test_signature_exact_bytes_method_path_and_time():
    body = '{"text":"₹ विश्वविद्यालय"}'.encode()
    headers = worker.signed_headers(SECRET, "post", "/webhook/catalog", body, now=1700000000)
    expected = hmac.new(SECRET.encode(), b"1700000000.POST./webhook/catalog." + body, hashlib.sha256).hexdigest()
    assert headers["X-Catalog-Signature"] == "sha256=" + expected
    for method, path, content in [("GET", "/webhook/catalog", body), ("POST", "/webhook/catalog/", body), ("POST", "/webhook/catalog", b"" )]:
        assert worker.signed_headers(SECRET, method, path, content, now=1700000000) != headers


def test_atomic_versions_across_uploads_and_rollback(factory):
    ids = [add_upload(factory) for _ in range(8)]
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: saved(factory, i, 101), ids))
    assert [job.version for job in jobs(factory)] == list(range(1, 9))
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CatalogPost)) == 1
        service.lock(db)
        publication = service.latest_publication(db, db.scalar(select(CatalogPost)))
        service.enqueue(db, publication, force=True)
        db.rollback()
    assert len(jobs(factory)) == 8
    assert saved(factory, ids[0], 101) is not None
    assert jobs(factory)[-1].version == 9


def test_lease_prevents_parallel_send_and_recovers_abandonment(factory):
    upload_id = add_upload(factory)
    event_id = saved(factory, upload_id, 101)
    claimed = worker.claim(factory, settings(), 1000)
    assert claimed["event_id"] == event_id
    assert worker.claim(factory, settings(), 1001) is None
    recovered = worker.claim(factory, settings(), 1000 + worker.LEASE_SECONDS + 1)
    assert recovered["body"] == claimed["body"] and recovered["token"] != claimed["token"]
    worker.receive(factory, claimed, None, 2000)
    assert jobs(factory)[0].lease_token == recovered["token"]


def test_receipt_404_resends_identical_post(factory):
    saved(factory, add_upload(factory), 101)
    client = Chatbot()
    worker.tick(factory, client=client, now=1000)
    client.code = 404
    worker.tick(factory, client=client, now=2000)
    client.code = 200
    worker.tick(factory, client=client, now=3000)
    assert [call[0] for call in client.calls] == ["POST", "GET", "POST"]
    assert client.calls[0][2]["content"] == client.calls[2][2]["content"]


@pytest.mark.parametrize("code", [401, 409, 413, 422, 301])
def test_permanent_http_errors_are_safe_and_not_retried(factory, code):
    saved(factory, add_upload(factory), 101)
    client = Chatbot(code=code)
    worker.tick(factory, client=client, now=1000)
    assert jobs(factory)[0].status == "failed"
    worker.tick(factory, client=client, now=9000)
    assert len(client.calls) == 1
    assert client.calls[0][2]["follow_redirects"] is False


@pytest.mark.parametrize("code", [429, 500, 503])
def test_transient_http_backoff(factory, code):
    saved(factory, add_upload(factory), 101)
    client = Chatbot(code=code)
    worker.tick(factory, client=client, now=1000)
    job = jobs(factory)[0]
    assert job.status == "queued" and 1000 < job.next_attempt < 1010


def test_failed_receiver_new_event_ignored_does_not_force_older_snapshot(factory, api):
    upload_id = add_upload(factory)
    saved(factory, upload_id, 101)
    client = Chatbot("failed")
    worker.tick(factory, client=client, now=1000)
    original = jobs(factory)[0]
    result = api.post(f"/catalog/uploads/{upload_id}/retry")
    assert result.status_code == 200
    assert jobs(factory)[0].body == original.body
    assert jobs(factory)[1].version == 2
    client.state = "ignored"
    worker.tick(factory, client=client, now=2000)
    assert jobs(factory)[1].status == "superseded"
    assert "not confirmed" in jobs(factory)[1].last_error
    assert api.post(f"/catalog/uploads/{upload_id}/retry").status_code == 400
    assert len(jobs(factory)) == 2


def test_parents_apply_before_children_and_mismatch_fails(factory):
    # Deliberately create child rows first: sender must select applied dependencies, not insertion order.
    course_upload = add_upload(factory, "course", program_name="Online MBA")
    saved(factory, course_upload, 202, university=[101])
    university_upload = add_upload(factory)
    saved(factory, university_upload, 101)
    spec_upload = add_upload(factory, "specialization", spec_name="Finance")
    saved(factory, spec_upload, 303, university=[101], course=[202])
    client = Chatbot("applied")
    worker.tick(factory, client=client, now=1000)
    assert json.loads(client.calls[-1][2]["content"])["entity_type"] == "university"
    worker.tick(factory, client=client, now=2000)
    assert json.loads(client.calls[-1][2]["content"])["entity_type"] == "course"
    worker.tick(factory, client=client, now=3000)
    assert json.loads(client.calls[-1][2]["content"])["entity_type"] == "specialization"
    with factory() as db:
        service.lock(db)
        publication = db.get(CatalogPublication, spec_upload)
        publication.university_id = "999"
        with pytest.raises(SyncError, match="different universities"):
            service.enqueue(db, publication, force=True)


def test_backfill_dry_run_dedup_resumption_and_coverage(factory, api):
    university = add_upload(factory)
    saved(factory, university, 101, enqueue=False)
    duplicate = add_upload(factory)
    saved(factory, duplicate, 101, enqueue=False)
    course = add_upload(factory, "course")
    saved(factory, course, 202, university=[101], enqueue=False)
    missing = add_upload(factory, "course")
    saved(factory, missing, 203, university=[999], enqueue=False)
    preview = api.post("/catalog/backfills/preview").json()
    assert preview["counts"] == dict(ready=2, blocked=1, existing=0, ineligible=0)
    assert "no site crawl" in preview["coverage"] and "999" in preview["posts"][-1]["error"]
    assert jobs(factory) == []
    result = api.post("/catalog/backfills").json()
    assert result["total"] == 2
    run_id = result["id"]
    client = Chatbot("applied")
    worker.tick(factory, client=client, now=1000)
    assert api.get(f"/catalog/backfills/{run_id}").json()["counts"]["synced"] == 1
    worker.tick(factory, client=client, now=2000)
    assert api.get(f"/catalog/backfills/{run_id}").json()["complete"]
    api.post("/catalog/backfills")
    assert len(jobs(factory)) == 2  # Resume/repeat doesn't allocate replacement events.


def test_reviewed_slug_and_explicit_clears_only(factory, api):
    upload_id = add_upload(factory, faqs=[])
    saved(factory, upload_id, 101, enqueue=False)
    assert api.put(f"/catalog/uploads/{upload_id}/settings", json=dict(catalog_slug="nmims", clear_fields=["faqs"])).status_code == 400
    response = api.put(f"/catalog/uploads/{upload_id}/settings", json=dict(catalog_slug="nmims", clear_fields=["faqs"], removals_approved=True))
    assert response.status_code == 200
    assert api.post(f"/catalog/uploads/{upload_id}/retry").status_code == 200
    body = json.loads(jobs(factory)[0].body)
    assert body["catalog_slug"] == "nmims" and body["clear_fields"] == ["faqs"]
    assert "catalog_slug" not in body["data"]
    assert api.get(f"/catalog/uploads/{upload_id}").json()["clear_fields"] == []
    assert api.put(f"/catalog/uploads/{upload_id}/settings", json=dict(clear_fields=["program_name"], removals_approved=True)).status_code == 400


def test_local_enqueue_failure_journal_recovers_without_wp_republication(factory, api, monkeypatch):
    upload_id = add_upload(factory)
    original = service.enqueue_safe
    def failed_insert(*args):
        raise RuntimeError("simulated SQL insert failure")
    monkeypatch.setattr(service, "enqueue_safe", failed_insert)
    result = publish(api, monkeypatch, upload_id)
    assert result["wp_status"] == "publish" and result["catalog_sync"]["status"] == "failed"
    assert len(list(recovery.directory().glob("*.json"))) == 1
    with factory() as db:
        assert json.loads(db.get(Upload, upload_id).payload)["_meta"]["wp_post_id"] == 101
    monkeypatch.setattr(service, "enqueue_safe", original)
    recovery.recover(factory)
    assert len(jobs(factory)) == 1
    recovery.recover(factory)
    assert len(jobs(factory)) == 1


def test_missing_ids_and_bad_canonical_keep_wordpress_success(factory, api, monkeypatch):
    upload_id = add_upload(factory, "course")
    result = publish(api, monkeypatch, upload_id, wp_result(202))
    assert result["wp_status"] == "publish"
    assert result["catalog_sync"]["status"] == "failed" and "linked_university" in result["catalog_sync"]["last_error"]
    assert not jobs(factory)
    result = wp_result(202, university=[101])
    result["link"] += "?secret=private"
    response = publish(api, monkeypatch, upload_id, result)
    assert response["catalog_sync"]["status"] == "failed"
    assert "private" not in response["catalog_sync"]["last_error"]


def test_legacy_reference_reconciliation_reads_only_and_retains_published_snapshot(factory, api, monkeypatch):
    upload_id = add_upload(factory, "course", program_name="Reviewed MBA")
    monkeypatch.setattr(wordpress_client, "read_catalog_references", lambda kind, source_id: wp_result(int(source_id), university=[101]))
    assert api.post(f"/catalog/uploads/{upload_id}/reconcile", json={"wp_post_id": "202"}).status_code == 400
    response = api.post(f"/catalog/uploads/{upload_id}/reconcile", json={"wp_post_id": "202", "reviewed": True})
    assert response.status_code == 200
    assert not jobs(factory)
    assert api.post(f"/catalog/uploads/{upload_id}/retry").status_code == 200
    assert json.loads(jobs(factory)[0].body)["data"]["program_name"] == "Reviewed MBA"
    with factory() as db:
        upload = db.get(Upload, upload_id)
        payload = json.loads(upload.payload)
        payload["program_name"] = "Unpublished edits"
        upload.payload = json.dumps(payload)
        db.commit()
    api.post(f"/catalog/uploads/{upload_id}/reconcile", json={"reviewed": True})
    api.post(f"/catalog/uploads/{upload_id}/retry")
    assert json.loads(jobs(factory)[-1].body)["data"]["program_name"] == "Reviewed MBA"


@pytest.mark.parametrize("base", ["http://example.com", "https://chatbot.test/prefix", "https://u:p@chatbot.test", "https://chatbot.test?x=1", "https://chatbot.test#fragment"])
def test_server_origin_restrictions(factory, monkeypatch, base):
    monkeypatch.setenv("CHATBOT_BASE_URL", base)
    with pytest.raises(SyncError):
        settings()


def test_localhost_development_only_and_site_binding(factory, monkeypatch):
    monkeypatch.setenv("CHATBOT_BASE_URL", "http://localhost:8001")
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SyncError):
        settings()
    monkeypatch.setenv("APP_ENV", "development")
    assert settings().base_url == "http://localhost:8001"
    saved(factory, add_upload(factory), 101)
    monkeypatch.setenv("WORDPRESS_SITE_URL", "https://another.test")
    with pytest.raises(SyncError, match="another WordPress"):
        saved(factory, add_upload(factory), 101)


def test_additive_migration_is_repeatable_and_preserves_uploads(factory):
    upload_id = add_upload(factory)
    service.migrate(factory.kw["bind"])
    service.migrate(factory.kw["bind"])
    with factory() as db:
        assert db.get(Upload, upload_id)
        assert db.get(CatalogLock, 1)


def test_outsize_snapshot_does_not_consume_version(factory):
    upload_id = add_upload(factory, about_content="x" * (2 * 1024 * 1024))
    with pytest.raises(SyncError, match="2 MiB"):
        saved(factory, upload_id, 101)
    assert not jobs(factory)


def test_unpublishing_flags_operator_action_and_stops_pending_send(factory, api, monkeypatch):
    upload_id = add_upload(factory)
    publish(api, monkeypatch, upload_id)
    response = publish(api, monkeypatch, upload_id, wp_result(status="draft"))
    assert response["catalog_sync"]["status"] == "not eligible/draft"
    client = Chatbot("applied")
    worker.tick(factory, client=client, now=1000)
    assert client.calls == [] and jobs(factory)[0].status == "failed"


def test_reviewed_slug_can_be_set_before_first_publish(factory, api, monkeypatch):
    upload_id = add_upload(factory)
    monkeypatch.setattr(wordpress_client, "is_configured", lambda: True)
    calls = []
    def remote(*args, **kwargs):
        calls.append(True)
        return wp_result()
    monkeypatch.setattr(wordpress_client, "publish_payload", remote)
    assert api.post(f"/publish/{upload_id}", json=dict(status="publish", catalog_slug="nmims")).status_code == 400
    assert not calls
    response = api.post(f"/publish/{upload_id}", json=dict(status="publish", catalog_slug="nmims", catalog_slug_reviewed=True))
    assert response.status_code == 200
    assert json.loads(jobs(factory)[0].body)["catalog_slug"] == "nmims"


def test_sender_config_and_response_redact_secret(factory, api, monkeypatch, caplog):
    upload_id = add_upload(factory)
    saved(factory, upload_id, 101)
    class SafeReceiver:
        def request(self, method, url, **kwargs):
            return httpx.Response(200, json=dict(event_id=jobs(factory)[0].event_id, status="failed", last_error=SECRET, warnings=[SECRET]))
    worker.tick(factory, client=SafeReceiver(), now=1000)
    response = api.get(f"/catalog/uploads/{upload_id}")
    assert SECRET not in response.text and "redacted" in response.text
    assert SECRET not in caplog.text
    assert SECRET not in repr(settings())
    assert api.put(f"/catalog/uploads/{upload_id}/settings", json=dict(CHATBOT_BASE_URL="https://attacker.test")).status_code == 422


def test_latest_snapshot_waits_for_latest_parent_application(factory):
    university = add_upload(factory)
    saved(factory, university, 101)
    client = Chatbot("applied")
    worker.tick(factory, client=client, now=1000)
    new_parent = add_upload(factory)
    saved(factory, new_parent, 101, enqueue=False)
    course = add_upload(factory, "course")
    saved(factory, course, 202, university=[101])
    worker.tick(factory, client=client, now=2000)
    assert len(client.calls) == 1
    assert "Waiting" in jobs(factory)[-1].last_error


def test_failed_sql_transaction_rolls_back_references_and_counter_together(factory):
    upload_id = add_upload(factory)
    with factory() as db:
        service.lock(db)
        upload = db.get(Upload, upload_id)
        publication = service.record_publication(db, upload, json.loads(upload.payload), wp_result(), "https://degreebaba.com", str(uuid4()), 1000)
        service.enqueue(db, publication)
        payload = json.loads(upload.payload)
        payload["_meta"] = {"wp_post_id": 101}
        upload.payload = json.dumps(payload)
        db.flush()
        db.rollback()
    with factory() as db:
        assert not db.get(CatalogPublication, upload_id)
        assert not db.scalar(select(CatalogPost))
        assert "_meta" not in json.loads(db.get(Upload, upload_id).payload)
    assert not jobs(factory)


def test_legacy_preview_requires_review_instead_of_syncing_unpublished_edits(factory, api):
    upload_id = add_upload(factory, source_id=101)
    with factory() as db:
        upload = db.get(Upload, upload_id)
        payload = json.loads(upload.payload)
        payload["_meta"].update(wp_status="publish", wp_post_url="https://degreebaba.com/catalog/101/")
        upload.payload = json.dumps(payload)
        db.commit()
    preview = api.post("/catalog/backfills/preview").json()
    assert preview["counts"]["blocked"] == 1 and preview["counts"]["ready"] == 0
    assert "legacy" in preview["posts"][0]["error"]
    assert api.post(f"/catalog/uploads/{upload_id}/retry").status_code == 400
    assert not jobs(factory)


def test_global_sender_lease_also_blocks_other_posts(factory):
    saved(factory, add_upload(factory), 101)
    saved(factory, add_upload(factory), 102)
    assert worker.claim(factory, settings(), 1000)
    assert worker.claim(factory, settings(), 1001) is None


def test_old_journal_does_not_auto_enqueue_new_manual_review(factory):
    upload_id = add_upload(factory)
    path, record = recovery.write(upload_id, "university", {"university_name": "Original"}, wp_result(), "https://degreebaba.com")
    with factory() as db:
        service.lock(db)
        upload = db.get(Upload, upload_id)
        service.record_publication(db, upload, {"university_name": "Reviewed legacy"}, wp_result(), "https://degreebaba.com", str(uuid4()), record["published_at"] + 1)
        db.commit()
    recovery.recover(factory)
    assert not path.exists() and not jobs(factory)


def test_startup_migration_and_sender_shutdown_are_isolated(factory, monkeypatch):
    import main
    monkeypatch.setattr(main, "engine", factory.kw["bind"])
    monkeypatch.setattr(main, "SessionLocal", factory)
    monkeypatch.setattr(main, "initialize_field_index", lambda: None)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        sender = app.state.catalog_worker
        assert sender.thread.is_alive()
    assert sender.stop.is_set() and not sender.thread.is_alive()
