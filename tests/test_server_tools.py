"""The two-tool surface: search returns addressable fragments, fetch returns pages."""

import dataclasses
import json

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


async def test_only_search_and_fetch_are_exposed():
    listed = await server.mcp.list_tools()
    assert {t.name for t in listed} == {"search", "fetch"}
    assert all(t.description for t in listed)


async def test_search_leads_with_a_grounding_note_then_the_results(tools):
    result = await tools.search("add an mcp server")
    assert len(result.content) == 2
    assert "не додумывай" in result.content[0].text  # the note comes first
    payload = json.loads(result.content[1].text)
    assert payload == result.structuredContent  # same data both ways


async def test_search_results_carry_the_convention_fields(tools):
    payload = (await tools.search("add an mcp server")).structuredContent
    top = payload["results"][0]
    assert set(top) == {"id", "title", "url", "text", "heading_path"}
    assert top["id"].startswith("user-guide/features/mcp#")
    assert top["url"].startswith("https://docs.example.test/docs/user-guide/features/mcp")
    assert isinstance(top["heading_path"], list)
    assert top["heading_path"][0] == "MCP Integration"


async def test_search_snippets_are_capped(tools, monkeypatch):
    monkeypatch.setattr(server, "SNIPPET_CHARS", 50)
    payload = (await tools.search("mcp server config")).structuredContent
    assert all(len(r["text"]) <= 50 for r in payload["results"])


async def test_search_misses_return_no_results_rather_than_noise(tools):
    assert (await tools.search("kubernetes helm chart xyzzy")).structuredContent["results"] == []


async def test_every_search_id_is_fetchable(tools):
    payload = (await tools.search("mcp")).structuredContent
    assert payload["results"]
    for hit in payload["results"]:
        page = (await tools.fetch(hit["id"])).structuredContent
        assert page["text"]
        assert hit["id"].startswith(page["id"])  # the fragment belongs to that page


async def test_fetch_returns_the_whole_page_with_metadata(tools):
    page = (await tools.fetch("user-guide/features/mcp")).structuredContent
    assert set(page) == {"id", "title", "url", "text", "metadata"}
    assert page["title"] == "MCP Integration"  # title from the docs index
    assert "hermes mcp add" in page["text"]
    assert "your privileges" in page["text"]  # the whole page, not one section
    meta = page["metadata"]
    assert meta["section"] == "user-guide"
    assert meta["nav_section"] == "Features"
    assert meta["truncated"] is False
    assert "Quick start" in meta["headings"]


async def test_fetch_accepts_a_path_a_fragment_id_and_a_url(tools):
    expected = "user-guide/features/mcp"
    for ref in (
        expected,
        f"{expected}#1",
        f"https://docs.example.test/docs/{expected}",
        "MCP Integration",
    ):
        assert (await tools.fetch(ref)).structuredContent["id"] == expected, ref


async def test_fetch_truncates_and_says_so(tools, monkeypatch):
    monkeypatch.setattr(server, "MAX_PAGE_CHARS", 120)
    page = (await tools.fetch("user-guide/features/mcp")).structuredContent
    assert len(page["text"]) == 120
    assert page["metadata"]["truncated"] is True
    assert page["metadata"]["total_chars"] > 120


async def test_unknown_id_is_rejected_with_guidance(tools):
    with pytest.raises(DocsInputError) as excinfo:
        await tools.fetch("no/such/page")
    assert "search" in str(excinfo.value)


async def test_out_of_range_fragment_falls_back_to_the_page(tools):
    page = (await tools.fetch("user-guide/features/mcp#999")).structuredContent
    assert page["id"] == "user-guide/features/mcp"


async def test_a_russian_query_is_told_to_try_english(tools):
    """The docs are English and the index lexical; an empty result must say why."""
    result = await tools.search("как подключить телеграм")
    assert result.structuredContent["results"] == []
    note = result.content[0].text
    assert "англоязычная" in note
    assert "search" in note  # tells the model to retry, not to give up


async def test_an_empty_english_query_gets_vocabulary_hints(tools):
    result = await tools.search("kubernetes helm chart xyzzy")
    assert result.structuredContent["results"] == []
    assert "gateway" in result.content[0].text
