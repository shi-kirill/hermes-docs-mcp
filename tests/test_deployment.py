"""Behaviour that only matters when the server is hosted rather than local."""

import dataclasses

import pytest

from hermes_docs_mcp import server
from hermes_docs_mcp.config import Config
from hermes_docs_mcp.store import DocsStore


def test_port_prefers_our_variable_then_the_host_one(monkeypatch):
    monkeypatch.delenv("HERMES_DOCS_MCP_PORT", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    assert server.resolve_port() == 8020
    monkeypatch.setenv("PORT", "10000")  # what Render sets
    assert server.resolve_port() == 10000
    monkeypatch.setenv("HERMES_DOCS_MCP_PORT", "8020")
    assert server.resolve_port() == 8020


def test_public_bind_needs_an_explicit_opt_in():
    server._validate_transport("stdio", "0.0.0.0")  # stdio never binds
    server._validate_transport("streamable-http", "127.0.0.1")
    with pytest.raises(RuntimeError) as excinfo:
        server._validate_transport("streamable-http", "0.0.0.0")
    assert "HERMES_DOCS_MCP_ALLOW_PUBLIC_BIND" in str(excinfo.value)
    server._validate_transport("streamable-http", "0.0.0.0", allow_public=True)


async def test_refresh_is_throttled(docs_server, tmp_path):
    """An exposed instance must not re-download on demand for anyone who asks."""
    http, handler = docs_server
    host, port = http.server_address[:2]
    cfg = Config(
        base_url=f"http://{host}:{port}",
        cache_dir=tmp_path / "cache",
        ttl_seconds=0,
        timeout=5.0,
        offline=False,
        min_refresh_seconds=300,
    )
    store = DocsStore(cfg)
    first = await store.refresh()
    assert first["refreshed"] is True

    hits = len(handler.hits)
    second = await store.refresh()
    assert second["throttled"] is True
    assert 0 < second["retry_after_seconds"] <= 300
    assert len(handler.hits) == hits  # nothing was fetched

    relaxed = DocsStore(dataclasses.replace(cfg, min_refresh_seconds=0))
    await relaxed.refresh()
    assert len(handler.hits) > hits  # the floor is what stopped it, not the cache


async def test_the_floor_starts_at_first_load(docs_server, tmp_path):
    """Loading the docs counts as a refresh, so a refresh right after is pointless."""
    http, handler = docs_server
    host, port = http.server_address[:2]
    store = DocsStore(
        Config(
            base_url=f"http://{host}:{port}",
            cache_dir=tmp_path / "cache",
            ttl_seconds=0,
            timeout=5.0,
            offline=False,
            min_refresh_seconds=300,
        )
    )
    await store.ready()
    hits = len(handler.hits)
    assert (await store.refresh())["throttled"] is True
    assert len(handler.hits) == hits
