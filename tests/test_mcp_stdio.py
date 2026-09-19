"""End-to-end check that the server speaks MCP over stdio with a real client."""

import os
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = {
    "hermes_docs_status",
    "hermes_docs_search",
    "hermes_docs_page",
    "hermes_docs_list",
    "hermes_docs_refresh",
}


@pytest.fixture
def params(seeded_cfg):
    env = {
        **os.environ,
        "HERMES_DOCS_MCP_CACHE_DIR": str(seeded_cfg.cache_dir),
        "HERMES_DOCS_MCP_BASE_URL": seeded_cfg.base_url,
        "HERMES_DOCS_MCP_OFFLINE": "1",
        "HERMES_DOCS_MCP_TRANSPORT": "stdio",
    }
    return StdioServerParameters(command=sys.executable, args=["-m", "hermes_docs_mcp"], env=env)


async def test_tools_are_listed_and_callable(params):
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        listed = await session.list_tools()
        names = {t.name for t in listed.tools}
        assert names >= EXPECTED_TOOLS
        for tool in listed.tools:
            assert tool.description  # every tool documents itself for the model

        result = await session.call_tool("hermes_docs_search", {"query": "mcp server", "limit": 2})
        assert result.isError is False
        assert "user-guide/features/mcp" in result.content[0].text

        page = await session.call_tool(
            "hermes_docs_page", {"page": "getting-started/installation"}
        )
        assert page.isError is False
        assert "Quick Install" in page.content[0].text


async def test_bad_arguments_are_rejected_by_the_schema(params):
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        too_many = await session.call_tool("hermes_docs_search", {"query": "mcp", "limit": 999})
        assert too_many.isError is True
        unknown = await session.call_tool("hermes_docs_page", {"page": "no/such/page"})
        assert unknown.isError is True
