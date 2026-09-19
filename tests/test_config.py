import pytest

from hermes_docs_mcp.config import DEFAULT_BASE_URL, load_config, validate_base_url
from hermes_docs_mcp.errors import DocsConfigError


def test_defaults(monkeypatch):
    for key in list(dict(**__import__("os").environ)):
        if key.startswith("HERMES_DOCS_MCP_"):
            monkeypatch.delenv(key, raising=False)
    cfg = load_config()
    assert cfg.base_url == DEFAULT_BASE_URL
    assert cfg.full_text_url.endswith("/llms-full.txt")
    assert cfg.index_url.endswith("/docs/llms.txt")
    assert cfg.offline is False


def test_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_DOCS_MCP_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("HERMES_DOCS_MCP_TTL", "60")
    monkeypatch.setenv("HERMES_DOCS_MCP_OFFLINE", "yes")
    cfg = load_config()
    assert cfg.cache_dir == tmp_path
    assert cfg.ttl_seconds == 60
    assert cfg.offline is True


def test_bad_ttl_is_rejected(monkeypatch):
    monkeypatch.setenv("HERMES_DOCS_MCP_TTL", "soon")
    with pytest.raises(DocsConfigError):
        load_config()


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.test",
        "https://",
        "https://user:pw@example.test",
        "http://169.254.169.254",  # cloud metadata over plain http
        "https://example.test?x=1",
    ],
)
def test_unsafe_base_urls_are_rejected(url):
    with pytest.raises(DocsConfigError):
        validate_base_url(url)


def test_loopback_http_is_allowed_for_tests():
    assert validate_base_url("http://127.0.0.1:8099/") == "http://127.0.0.1:8099"
