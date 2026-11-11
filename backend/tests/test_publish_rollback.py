"""A new post is created as a draft and goes live only together with its
acf data. If WordPress rejects that data, the empty post is deleted again:
failed publishes used to leave empty live pages on staging (and took their
slug, so the retry became "data-science-2")."""

from __future__ import annotations

import json

import httpx
import pytest

from pipeline import wordpress_client as wc

SITE = "https://wp.test"
PAYLOAD = {"program_name": "Amity University Online MBA", "total_fee": "INR 1,99,000 /-"}


class Site:
    def __init__(self, acf_status=200, delete_status=200, acf_error=None):
        self.requests = []
        self.acf_status, self.delete_status, self.acf_error = acf_status, delete_status, acf_error

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, dict(request.url.params), body))
        if request.method == "OPTIONS":
            return httpx.Response(200, json={"schema": {"properties": {"acf": {"properties": {
                "program_name": {"type": ["string", "null"]}, "total_fee": {"type": ["string", "null"]}}}}}})
        if request.method == "GET":
            return httpx.Response(200, json=[], headers={"X-WP-TotalPages": "1"})
        if request.method == "DELETE":
            return httpx.Response(self.delete_status, json={"deleted": self.delete_status == 200})
        if request.url.path.endswith("/course"):  # create
            return httpx.Response(201, json={"id": 501, "status": body["status"], "link": f"{SITE}/?p=501"})
        if self.acf_error:
            raise self.acf_error
        if self.acf_status >= 400:
            return httpx.Response(self.acf_status, json={"code": "rest_invalid_param", "message": "Invalid parameter(s): acf"})
        return httpx.Response(200, json={"id": 501, "status": body.get("status"), "link": f"{SITE}/course/amity/"})


@pytest.fixture
def site(monkeypatch):
    def make(**kw):
        s = Site(**kw)
        transport = httpx.MockTransport(s.handle)

        class Shim:
            def Client(self, *a, **k):  # noqa: N802
                k.pop("transport", None)
                return httpx.Client(*a, transport=transport, **k)

            def __getattr__(self, name):
                return getattr(httpx, name)

        monkeypatch.setattr(wc, "httpx", Shim())
        monkeypatch.setenv("WORDPRESS_SITE_URL", SITE)
        monkeypatch.setenv("WORDPRESS_APP_USER", "u")
        monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "p")
        for cache in (wc._post_title_cache, wc._post_title_cache_ts, wc._term_id_cache):
            cache.clear()
        return s
    return make


@pytest.mark.usefixtures("allow_mock_transport")
def test_new_post_is_created_as_draft_and_goes_live_with_its_fields(site) -> None:
    s = site()
    result = wc.publish_payload(dict(PAYLOAD), "course", status="publish")
    posts = [r for r in s.requests if r[0] == "POST"]
    assert posts[0][1].endswith("/course") and posts[0][3]["status"] == "draft"
    assert posts[1][3]["status"] == "publish" and posts[1][3]["acf"]["total_fee"] == "INR 1,99,000 /-"
    assert result["status"] == "publish"
    assert not [r for r in s.requests if r[0] == "DELETE"]


@pytest.mark.usefixtures("allow_mock_transport")
def test_rejected_fields_delete_the_empty_post(site) -> None:
    s = site(acf_status=400)
    with pytest.raises(RuntimeError, match="Invalid parameter"):
        wc.publish_payload(dict(PAYLOAD), "course", status="publish")
    deletes = [r for r in s.requests if r[0] == "DELETE"]
    assert len(deletes) == 1 and deletes[0][1].endswith("/course/501") and deletes[0][2] == {"force": "true"}


@pytest.mark.usefixtures("allow_mock_transport")
def test_network_error_on_the_fields_also_deletes_it(site) -> None:
    s = site(acf_error=httpx.ConnectError("boom"))
    with pytest.raises(httpx.ConnectError):
        wc.publish_payload(dict(PAYLOAD), "course", status="publish")
    assert [r for r in s.requests if r[0] == "DELETE"]


@pytest.mark.usefixtures("allow_mock_transport")
def test_failed_delete_still_reports_the_original_error(site, caplog) -> None:
    site(acf_status=400, delete_status=500)
    with pytest.raises(RuntimeError, match="Invalid parameter"):
        wc.publish_payload(dict(PAYLOAD), "course", status="publish")
    assert "PUBLISH_ROLLBACK_FAILED" in caplog.text
