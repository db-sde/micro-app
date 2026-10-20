from dataclasses import dataclass, field
import os
from urllib.parse import urlsplit


class SyncError(ValueError):
    """Only fixed safe messages or validated IDs belong in this exception."""


def origin(value):
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        raise SyncError("Invalid server origin configuration.") from None
    if not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise SyncError("Configure a server origin without credentials, path, query or fragment.")
    local = url.hostname in ("localhost", "127.0.0.1", "::1")
    development = os.getenv("APP_ENV", "production") == "development"
    if url.scheme != "https" and not (url.scheme == "http" and local and development):
        raise SyncError("Chatbot transport requires HTTPS; localhost HTTP requires APP_ENV=development.")
    host = f"[{url.hostname}]" if ":" in url.hostname else url.hostname
    return f"{url.scheme}://{host}" + (f":{port}" if port else "")


@dataclass(frozen=True)
class Config:
    base_url: str
    secret: str = field(repr=False)
    site: str = ""
    hosts: frozenset = frozenset()


def settings():
    base = os.getenv("CHATBOT_BASE_URL", "").strip()
    secret = os.getenv("CHATBOT_CATALOG_WEBHOOK_SECRET", "")
    if not base or not secret:
        return None
    if len(secret.strip()) < 32:
        raise SyncError("CHATBOT_CATALOG_WEBHOOK_SECRET must contain at least 32 characters.")
    # WP may be installed in a subdirectory; this is a site identity, not a webhook destination.
    site = os.getenv("WORDPRESS_SITE_URL", "").strip().rstrip("/")
    wp = urlsplit(site)
    if not wp.hostname or wp.username or wp.password or wp.query or wp.fragment:
        raise SyncError("Configure WORDPRESS_SITE_URL before enabling catalog sync.")
    hosts = frozenset(h.strip().lower() for h in os.getenv(
        "CHATBOT_CATALOG_SOURCE_HOSTS", "degreebaba.com,www.degreebaba.com"
    ).split(",") if h.strip())
    return Config(origin(base), secret, site, hosts)
