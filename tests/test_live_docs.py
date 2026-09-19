"""Opt-in check against the real docs site: HERMES_DOCS_MCP_LIVE=1 uv run pytest -k live."""

import os

import pytest

from hermes_docs_mcp.config import DEFAULT_BASE_URL, Config
from hermes_docs_mcp.store import DocsStore

pytestmark = pytest.mark.skipif(
    os.environ.get("HERMES_DOCS_MCP_LIVE") != "1", reason="live network test is opt-in"
)


async def test_live_site_still_matches_our_parser(tmp_path):
    cfg = Config(
        base_url=DEFAULT_BASE_URL,
        cache_dir=tmp_path / "cache",
        ttl_seconds=0,
        timeout=60.0,
        offline=False,
    )
    store = DocsStore(cfg)
    corpus = await store.ready()
    # Shape assertions, not exact counts: the docs grow.
    assert len(corpus.pages) > 150
    assert len(corpus.chunks) > 1000
    assert "user-guide/features/mcp" in corpus.by_path
    assert {"getting-started", "user-guide", "developer-guide", "reference"} <= set(corpus.sections)
    described = [p for p in corpus.pages if p.description]
    assert len(described) > 100  # docs/llms.txt still joins onto pages by URL
    hits = (await store.searcher()).search("configure telegram bot token", limit=3)
    assert hits and hits[0].page.path.startswith("user-guide/messaging")
