"""Configuration for the Hermes docs MCP server.

Everything comes from the environment, so one package serves both a laptop
(Claude Code, stdio) and a VPS (Hermes, stdio or loopback HTTP).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .errors import DocsConfigError

DEFAULT_BASE_URL = "https://hermes-agent.nousresearch.com"
DEFAULT_TTL_SECONDS = 24 * 3600
# An exposed instance must not become a download button for anyone who finds
# the URL, so refreshes have a floor regardless of who asks.
DEFAULT_MIN_REFRESH_SECONDS = 300
DEFAULT_TIMEOUT = 30.0
# The real file is ~5 MB; the cap only exists so a redirect to something huge
# cannot fill the disk.
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


@dataclass(frozen=True)
class Config:
    base_url: str
    cache_dir: Path
    ttl_seconds: int
    timeout: float
    offline: bool
    min_refresh_seconds: int

    @property
    def full_text_url(self) -> str:
        return f"{self.base_url}/llms-full.txt"

    @property
    def index_url(self) -> str:
        return f"{self.base_url}/docs/llms.txt"


def _default_cache_dir() -> Path:
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "hermes-docs-mcp"


def validate_base_url(raw: str) -> str:
    """Reject anything that is not a plain https origin.

    The server fetches this URL unattended, so it must not become a lever for
    reaching internal hosts or embedding credentials. Plain http is allowed
    only for loopback, which is what the tests use.
    """
    url = raw.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise DocsConfigError(f"base URL must be http(s), got {raw!r}")
    if not parsed.netloc:
        raise DocsConfigError(f"base URL has no host: {raw!r}")
    if parsed.username or parsed.password:
        raise DocsConfigError("base URL must not embed credentials")
    if parsed.query or parsed.fragment:
        raise DocsConfigError("base URL must not carry a query or fragment")
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in LOOPBACK_HOSTS:
        raise DocsConfigError("plain http is only allowed for loopback hosts")
    return url


def _int_env(name: str, default: int, *, minimum: int = 0) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise DocsConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise DocsConfigError(f"{name} must be >= {minimum}")
    return value


def bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_config() -> Config:
    base_url = validate_base_url(os.environ.get("HERMES_DOCS_MCP_BASE_URL", DEFAULT_BASE_URL))
    cache_raw = os.environ.get("HERMES_DOCS_MCP_CACHE_DIR")
    cache_dir = Path(cache_raw).expanduser() if cache_raw else _default_cache_dir()
    return Config(
        base_url=base_url,
        cache_dir=cache_dir,
        ttl_seconds=_int_env("HERMES_DOCS_MCP_TTL", DEFAULT_TTL_SECONDS),
        timeout=float(_int_env("HERMES_DOCS_MCP_TIMEOUT", int(DEFAULT_TIMEOUT), minimum=1)),
        offline=bool_env("HERMES_DOCS_MCP_OFFLINE"),
        min_refresh_seconds=_int_env(
            "HERMES_DOCS_MCP_MIN_REFRESH", DEFAULT_MIN_REFRESH_SECONDS
        ),
    )
