import http.server
import threading
from pathlib import Path

import pytest

from hermes_docs_mcp import fetcher
from hermes_docs_mcp.config import Config
from hermes_docs_mcp.errors import DocsFetchError, DocsOfflineError

from .conftest import FULL_TEXT, INDEX_TEXT


class _Handler(http.server.BaseHTTPRequestHandler):
    bodies: dict[str, str] = {}
    etag = '"v1"'
    hits: list[str] = []
    fail_status: int | None = None

    def log_message(self, *args):  # keep test output clean
        pass

    def do_GET(self):  # noqa: N802 - stdlib naming
        type(self).hits.append(self.path)
        if type(self).fail_status:
            self.send_response(type(self).fail_status)
            self.end_headers()
            return
        body = type(self).bodies.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        if self.headers.get("If-None-Match") == type(self).etag:
            self.send_response(304)
            self.send_header("ETag", type(self).etag)
            self.end_headers()
            return
        payload = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("ETag", type(self).etag)
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def docs_server():
    _Handler.bodies = {"/llms-full.txt": FULL_TEXT, "/docs/llms.txt": INDEX_TEXT}
    _Handler.etag = '"v1"'
    _Handler.hits = []
    _Handler.fail_status = None
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server, _Handler
    server.shutdown()
    server.server_close()


def _cfg(server, tmp_path: Path, **kw) -> Config:
    host, port = server.server_address[:2]
    return Config(
        base_url=f"http://{host}:{port}",
        cache_dir=tmp_path / "cache",
        ttl_seconds=kw.pop("ttl_seconds", 3600),
        timeout=5.0,
        offline=kw.pop("offline", False),
    )


async def test_refresh_downloads_and_caches(docs_server, tmp_path):
    server, _ = docs_server
    cfg = _cfg(server, tmp_path)
    report = await fetcher.refresh(cfg)
    assert report["changed"] is True
    assert (cfg.cache_dir / "llms-full.txt").read_text(encoding="utf-8") == FULL_TEXT
    assert (cfg.cache_dir / "docs-llms.txt").read_text(encoding="utf-8") == INDEX_TEXT
    state = fetcher.cache_state(cfg)
    assert state["complete"] is True and state["stale"] is False


async def test_second_refresh_uses_conditional_requests(docs_server, tmp_path):
    server, handler = docs_server
    cfg = _cfg(server, tmp_path)
    await fetcher.refresh(cfg)
    report = await fetcher.refresh(cfg)
    assert report["changed"] is False
    assert all(r["status"] == 304 for r in report["files"].values())


async def test_changed_etag_pulls_new_content(docs_server, tmp_path):
    server, handler = docs_server
    cfg = _cfg(server, tmp_path)
    await fetcher.refresh(cfg)
    handler.etag = '"v2"'
    handler.bodies["/llms-full.txt"] = FULL_TEXT + "\n<!-- source: website/docs/new.md -->\n# New\n"
    report = await fetcher.refresh(cfg)
    assert report["changed"] is True
    assert "# New" in (cfg.cache_dir / "llms-full.txt").read_text(encoding="utf-8")


async def test_ensure_cached_skips_network_when_fresh(docs_server, tmp_path):
    server, handler = docs_server
    cfg = _cfg(server, tmp_path)
    await fetcher.ensure_cached(cfg)
    before = len(handler.hits)
    result = await fetcher.ensure_cached(cfg)
    assert result["refreshed"] is False
    assert len(handler.hits) == before


async def test_stale_cache_survives_a_failing_site(docs_server, tmp_path):
    server, handler = docs_server
    cfg = _cfg(server, tmp_path, ttl_seconds=0)
    await fetcher.refresh(cfg)
    handler.fail_status = 503
    result = await fetcher.ensure_cached(cfg)
    assert result["fetch_failed"] is True
    assert result["cache"]["complete"] is True


async def test_missing_cache_and_failing_site_raises(docs_server, tmp_path):
    server, handler = docs_server
    handler.fail_status = 503
    with pytest.raises(DocsFetchError):
        await fetcher.ensure_cached(_cfg(server, tmp_path))


async def test_offline_without_cache_raises(docs_server, tmp_path):
    server, _ = docs_server
    with pytest.raises(DocsOfflineError):
        await fetcher.ensure_cached(_cfg(server, tmp_path, offline=True))


async def test_offline_with_cache_works(docs_server, tmp_path):
    server, handler = docs_server
    cfg = _cfg(server, tmp_path)
    await fetcher.refresh(cfg)
    offline = Config(**{**cfg.__dict__, "offline": True, "ttl_seconds": 0})
    hits = len(handler.hits)
    result = await fetcher.ensure_cached(offline)
    assert result["offline"] is True and len(handler.hits) == hits
    with pytest.raises(DocsOfflineError):
        await fetcher.refresh(offline)


async def test_oversized_download_is_refused(docs_server, tmp_path, monkeypatch):
    server, handler = docs_server
    monkeypatch.setattr(fetcher, "MAX_DOWNLOAD_BYTES", 10)
    with pytest.raises(DocsFetchError):
        await fetcher.refresh(_cfg(server, tmp_path))


async def test_empty_body_is_refused(docs_server, tmp_path):
    server, handler = docs_server
    handler.bodies["/llms-full.txt"] = "   "
    with pytest.raises(DocsFetchError):
        await fetcher.refresh(_cfg(server, tmp_path))
