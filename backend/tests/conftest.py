"""Shared pytest fixtures and safety rails.

SAFETY: backend/.env holds REAL production credentials (WordPress app
password, Cloudinary, OpenAI, Neon Postgres) and every pipeline module
calls load_dotenv() at import time. Without the guards below, a test that
accidentally reaches a network code path would publish to the live
WordPress site or burn API credits. So:

  * `_scrub_live_credentials` (autouse) blanks every outbound credential
    for the whole session — any accidental live call fails fast with a
    config error instead of hitting production.
  * `_no_network` (autouse) replaces httpx's transport entrypoints with a
    raiser, so an un-mocked HTTP call is a loud test failure rather than a
    silent real request.

Tests that legitimately exercise HTTP paths inject their own fake client
(see `fake_httpx_client`), which bypasses both guards deliberately.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

# Make `acf`, `pipeline`, `db`, `main` importable regardless of the
# directory pytest was invoked from (repo root or backend/).
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


_CREDENTIAL_ENV_VARS = (
    "WORDPRESS_SITE_URL",
    "WORDPRESS_APP_USER",
    "WORDPRESS_APP_PASSWORD",
    "CLOUDINARY_URL",
    "CLOUDINARY_CLOUD_NAME",
    "CLOUDINARY_API_KEY",
    "CLOUDINARY_API_SECRET",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "CHATBOT_BASE_URL",
    "CHATBOT_CATALOG_WEBHOOK_SECRET",
    "CHATBOT_CATALOG_SOURCE_HOSTS",
)


# Guard collection-time imports too: dotenv loads before session fixtures run.
import tempfile
_TEST_ROOT = tempfile.mkdtemp(prefix="degreebaba-tests-")
for _var in _CREDENTIAL_ENV_VARS:
    os.environ[_var] = ""
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_ROOT}/collection.db"
os.environ["CATALOG_RECOVERY_DIR"] = f"{_TEST_ROOT}/recovery"


@pytest.fixture(autouse=True, scope="session")
def _scrub_live_credentials() -> None:
    """Blank real credentials for the entire test session."""
    for var in _CREDENTIAL_ENV_VARS:
        os.environ[var] = ""


@pytest.fixture(autouse=True)
def _no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly on any un-mocked outbound HTTP request.

    FastAPI's TestClient is itself an httpx.Client (over an in-process
    ASGI transport, so it never touches the network). Tests that use it
    opt out with @pytest.mark.allow_httpx.
    """
    import httpx

    def _blocked(*args: Any, **kwargs: Any):
        raise AssertionError(
            "Un-mocked network call attempted during a test. Inject a fake "
            "client instead of calling out to a real service."
        )

    original_send = httpx.Client.send

    def guarded_send(client, *args, **kwargs):
        if request.node.get_closest_marker("allow_httpx") and type(client._transport).__module__ == "starlette.testclient":
            return original_send(client, *args, **kwargs)
        return _blocked()

    monkeypatch.setattr(httpx.Client, "send", guarded_send)
    monkeypatch.setattr(httpx.AsyncClient, "send", _blocked)


@pytest.fixture(autouse=True)
def _reset_wordpress_caches() -> None:
    """Clear wordpress_client's module-level caches between tests.

    These are process-lifetime globals (post title lists, live ACF field
    types). Leaking them across tests makes results order-dependent — and
    a stale one of these was the exact production bug that stopped
    linked_university from ever resolving, so tests must not paper over it.
    """
    from pipeline import wordpress_client as wc

    wc._post_title_cache.clear()
    wc._post_title_cache_ts.clear()
    yield
    wc._post_title_cache.clear()
    wc._post_title_cache_ts.clear()


class FakeResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(
        self,
        json_data: Any = None,
        status_code: int = 200,
        headers: dict[str, str] | None = None,
        text: str = "",
    ) -> None:
        self._json = json_data if json_data is not None else []
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text

    def json(self) -> Any:
        return self._json


class FakeClient:
    """Context-manager stand-in for httpx.Client.

    Records every request and replays canned responses. `responses` may be
    a single FakeResponse (returned for every call) or a list consumed in
    order.
    """

    def __init__(self, responses: Any = None, **_: Any) -> None:
        if responses is None:
            responses = FakeResponse([])
        self._responses = responses if isinstance(responses, list) else [responses]
        self._index = 0
        self.calls: list[dict[str, Any]] = []

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def _next(self) -> FakeResponse:
        if self._index < len(self._responses):
            resp = self._responses[self._index]
        else:
            resp = self._responses[-1]
        self._index += 1
        return resp

    def get(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, **kwargs})
        return self._next()

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"method": "POST", "url": url, **kwargs})
        return self._next()


@pytest.fixture
def fake_httpx_client(monkeypatch: pytest.MonkeyPatch):
    """Patch wordpress_client's httpx.Client with a scripted fake.

    Usage::

        client = fake_httpx_client([FakeResponse([...]), FakeResponse([])])
        ...
        assert client.calls[0]["url"].endswith("/university")
    """

    def _install(responses: Any) -> FakeClient:
        from pipeline import wordpress_client as wc

        created: list[FakeClient] = []

        def _factory(*args: Any, **kwargs: Any) -> FakeClient:
            client = FakeClient(responses)
            created.append(client)
            return client

        monkeypatch.setattr(wc.httpx, "Client", _factory)
        # Expose the most recently created client for assertions.
        holder = FakeClient(responses)
        holder.created = created  # type: ignore[attr-defined]
        return holder

    return _install


@pytest.fixture
def wp_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide dummy (non-production) WordPress credentials."""
    monkeypatch.setenv("WORDPRESS_SITE_URL", "https://wp.test")
    monkeypatch.setenv("WORDPRESS_APP_USER", "test-user")
    monkeypatch.setenv("WORDPRESS_APP_PASSWORD", "test-pass")


# Captured at import, before the autouse network guard patches httpx.
import httpx as _httpx  # noqa: E402

_ORIGINAL_SEND = _httpx.Client.send


@pytest.fixture
def allow_mock_transport(monkeypatch):
    """Let only in-memory MockTransport clients through the network guard
    (e.g. the fake WordPress in evals/projection.py)."""
    def send(client, *args, **kwargs):
        if isinstance(client._transport, _httpx.MockTransport):
            return _ORIGINAL_SEND(client, *args, **kwargs)
        raise AssertionError("real network call attempted")
    monkeypatch.setattr(_httpx.Client, "send", send)
