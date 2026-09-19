import dataclasses

import pytest

from hermes_docs_mcp import server
from hermes_docs_mcp.errors import DocsInputError
from hermes_docs_mcp.store import DocsStore


@pytest.fixture
def tools(monkeypatch, seeded_cfg):
    """Point the module-level store at the seeded fixture cache, network disabled."""
    cfg = dataclasses.replace(seeded_cfg, offline=True)
    monkeypatch.setattr(server, "_STORE", DocsStore(cfg))
    return server


async def test_status_reports_the_cache_without_network(tools):
    status = await tools.hermes_docs_status()
    assert status["complete"] is True
    assert status["offline"] is True
    assert status["loaded"] is False  # nothing parsed yet


async def test_search_returns_ranked_results_with_urls(tools):
    result = await tools.hermes_docs_search("add an mcp server", limit=5)
    assert result["count"] >= 1
    top = result["results"][0]
    assert top["path"] == "user-guide/features/mcp"
    assert top["url"].startswith("https://docs.example.test/docs/user-guide/features/mcp")
    assert top["snippet"]
    assert top["score"] > 0


async def test_search_anchors_link_to_the_heading(tools):
    result = await tools.hermes_docs_search("trust model manifest", limit=3)
    assert any(r["url"].endswith("#trust-model") for r in result["results"])


async def test_search_on_unknown_page_is_rejected(tools):
    with pytest.raises(DocsInputError):
        await tools.hermes_docs_search("anything", page="no/such/page")


async def test_page_returns_markdown_and_metadata(tools):
    page = await tools.hermes_docs_page("user-guide/features/mcp")
    assert page["title"] == "MCP Integration"  # title from the docs index
    assert page["description"] == "Connect Hermes to MCP servers"
    assert "hermes mcp add" in page["markdown"]
    assert page["truncated"] is False and page["next_offset"] is None
    assert "Quick start" in page["headings"]


async def test_page_truncates_and_pages_through(tools):
    first = await tools.hermes_docs_page("user-guide/features/mcp", max_chars=500)
    assert first["truncated"] is True
    assert first["next_offset"] == first["returned_chars"]
    second = await tools.hermes_docs_page(
        "user-guide/features/mcp", max_chars=500, offset=first["next_offset"]
    )
    assert second["offset"] == first["next_offset"]
    assert second["markdown"] and second["markdown"] != first["markdown"]


async def test_page_can_return_one_heading(tools):
    section = await tools.hermes_docs_page("user-guide/features/mcp", heading="Trust model")
    assert section["heading"] == "Trust model"
    assert "your privileges" in section["markdown"]
    assert "hermes mcp add" not in section["markdown"]


async def test_unknown_page_and_heading_raise(tools):
    with pytest.raises(DocsInputError):
        await tools.hermes_docs_page("nope")
    with pytest.raises(DocsInputError) as excinfo:
        await tools.hermes_docs_page("user-guide/features/mcp", heading="Nope")
    assert "Quick start" in str(excinfo.value)  # error lists what is available


async def test_list_returns_toc_with_sections(tools):
    listing = await tools.hermes_docs_list()
    assert listing["count"] == 4
    assert "getting-started" in listing["sections"]
    assert "Features" in listing["nav_sections"]


async def test_list_filters_by_section_and_query(tools):
    by_section = await tools.hermes_docs_list(section="getting-started")
    assert [p["path"] for p in by_section["pages"]] == ["getting-started/installation"]
    by_query = await tools.hermes_docs_list(query="mcp")
    assert [p["path"] for p in by_query["pages"]] == ["user-guide/features/mcp"]


async def test_list_reports_truncation(tools):
    listing = await tools.hermes_docs_list(limit=1)
    assert listing["count"] == 4 and listing["truncated"] is True
    assert len(listing["pages"]) == 1


async def test_refresh_is_blocked_offline(tools):
    from hermes_docs_mcp.errors import DocsOfflineError

    with pytest.raises(DocsOfflineError):
        await tools.hermes_docs_refresh()


def test_http_transport_must_stay_on_loopback():
    server._validate_transport("stdio", "0.0.0.0")  # stdio never binds
    server._validate_transport("streamable-http", "127.0.0.1")
    with pytest.raises(RuntimeError):
        server._validate_transport("streamable-http", "0.0.0.0")
