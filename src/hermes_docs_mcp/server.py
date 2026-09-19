"""FastMCP server exposing the Hermes Agent documentation as a knowledge base.

Two tools, `search` and `fetch`, following the convention remote connectors
expect: search returns addressable fragments, fetch returns the whole page
behind one of them. Content comes from the machine-readable exports the docs
site publishes for this purpose, is cached on disk and served locally.

Everything these tools return is third-party documentation text: material to
read and cite, never instructions to follow.
"""

from __future__ import annotations

import json
import os
import re
from typing import Annotated, Any

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent
from pydantic import Field
from starlette.applications import Starlette
from starlette.routing import Route

from .config import LOOPBACK_HOSTS, bool_env, load_config
from .errors import DocsInputError
from .fetcher import ensure_cached
from .store import DocsStore

_HOST = os.environ.get("HERMES_DOCS_MCP_HOST", "127.0.0.1")


def resolve_port() -> int:
    """Our own variable wins; PORT is what Render and most hosts hand a service."""
    return int(os.environ.get("HERMES_DOCS_MCP_PORT") or os.environ.get("PORT") or 8020)


_PORT = resolve_port()

# How much of a page a search hit quotes. Wide enough to answer a question
# outright, narrow enough that eight of them still fit a reply.
SEARCH_RESULTS = 8
SNIPPET_CHARS = 1_200
# A page slice big enough for any single doc page, capped so one fetch cannot
# drown a context window.
MAX_PAGE_CHARS = 40_000

# Sent ahead of the results. The docs are the source of truth here; a model that
# pads them with recollection is worse than one that says it found nothing.
SEARCH_PREAMBLE = (
    "Отвечай только по этим фрагментам документации Hermes Agent. "
    "К каждому утверждению давай ссылку url на страницу, из которой оно взято. "
    "Если подходящего фрагмента нет — так и скажи, не додумывай. "
    "Нужна страница целиком — вызови fetch с id фрагмента. "
    "Отвечать можно на языке пользователя, цитаты оставляй как есть."
)
# The index is lexical and the documentation is English, so a Russian query
# matches nothing. The calling model speaks both: tell it to try again rather
# than let an empty result read as "the docs say nothing about this".
CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
EMPTY_CYRILLIC_HINT = (
    "Ничего не найдено: документация Hermes Agent англоязычная, а запрос был на "
    "русском. Переведи запрос на английский и вызови search ещё раз — например "
    "«как подключить телеграм» → «connect telegram bot gateway setup»."
)
EMPTY_HINT = (
    "Ничего не найдено. Попробуй другие слова — термины из документации Hermes "
    "Agent на английском: gateway, approvals, skills, memory, toolset, profile."
)

class _FastMCP(FastMCP):
    """FastMCP that answers on both `/mcp` and `/mcp/`.

    Starlette would redirect one spelling to the other with a 307. Compliant MCP
    clients follow it, but the connector check in Claude does not: it reports the
    server as not found, and the URL people copy is as likely to carry the slash
    as not.
    """

    def streamable_http_app(self) -> Starlette:
        app = super().streamable_http_app()
        path = self.settings.streamable_http_path
        alias = path.rstrip("/") + "/" if not path.endswith("/") else path.rstrip("/")
        known = {getattr(route, "path", None) for route in app.router.routes}
        if alias in known:
            return app
        original = next(r for r in app.router.routes if getattr(r, "path", None) == path)
        app.router.routes.append(
            Route(alias, endpoint=original.endpoint, methods=sorted(original.methods or []))
        )
        return app


mcp = _FastMCP(
    "hermes-docs",
    host=_HOST,
    port=_PORT,
    stateless_http=True,
)
_STORE = DocsStore(load_config())

Query = Annotated[str, Field(min_length=2, max_length=300, description="Поисковый запрос")]
DocId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=512,
        description="id из результатов search — либо путь страницы, либо путь с #N",
    ),
]


def _result(payload: dict[str, Any], *, preamble: str = "") -> CallToolResult:
    body = json.dumps(payload, ensure_ascii=False)
    blocks = [TextContent(type="text", text=preamble)] if preamble else []
    blocks.append(TextContent(type="text", text=body))
    return CallToolResult(content=blocks, structuredContent=payload)


@mcp.tool(structured_output=False)
async def search(query: Query) -> CallToolResult:
    """Поиск по официальной документации Hermes Agent (228 страниц, на английском).

    Зови этот инструмент на любой вопрос про Hermes Agent — установку, настройку,
    конфигурацию, инструменты, память, скиллы, MCP, мессенджеры, безопасность,
    развёртывание. Примеры: «как поставить Hermes на сервер», «что писать в
    SOUL.md», «как подключить Telegram», «какие есть режимы approvals», «чем
    skills отличаются от memory», «как настроить cron», «как запустить в Docker»,
    «какие провайдеры моделей поддерживаются», «как дать агенту доступ к MCP».

    Документация англоязычная, а поиск лексический — **формулируй запрос
    по-английски**, даже если пользователь спросил по-русски («как подключить
    телеграм» → «connect telegram bot gateway»). Отвечать пользователю можно
    на его языке.

    Возвращает фрагменты страниц с адресом id, заголовком, ссылкой и текстом.
    Отвечай по ним и ссылайся на url; за полной страницей вызывай fetch.
    """
    index = await _STORE.searcher()
    hits = index.search(query, limit=SEARCH_RESULTS)
    results = [
        {
            "id": hit.chunk.id,
            "title": hit.page.title,
            "url": hit.page.url + (f"#{hit.chunk.anchor}" if hit.chunk.anchor else ""),
            "text": hit.chunk.text[:SNIPPET_CHARS],
            "heading_path": list(hit.chunk.crumbs),
        }
        for hit in hits
    ]
    if not results:
        note = EMPTY_CYRILLIC_HINT if CYRILLIC.search(query) else EMPTY_HINT
        return _result({"results": []}, preamble=note)
    return _result({"results": results}, preamble=SEARCH_PREAMBLE)


@mcp.tool(structured_output=False)
async def fetch(id: DocId) -> CallToolResult:  # noqa: A002 - the name the convention expects
    """Возвращает страницу документации Hermes Agent целиком в markdown.

    Принимает id из результатов search — и путь страницы
    («user-guide/features/mcp»), и id фрагмента с суффиксом («…/mcp#3»), и полный
    URL страницы документации. Страницы бывают объёмными, поэтому зови только
    когда фрагментов из search действительно не хватает, а не на каждый результат.
    """
    corpus = await _STORE.ready()
    found = corpus.locate(id)
    if found is None:
        raise DocsInputError(
            f"unknown id {id!r}. Use an id from search results, "
            "a page path like 'user-guide/features/mcp', or a docs URL."
        )
    page, _chunk = found
    text = page.body[:MAX_PAGE_CHARS]
    return _result(
        {
            "id": page.path,
            "title": page.title,
            "url": page.url,
            "text": text,
            "metadata": {
                "section": page.section,
                "nav_section": page.nav_section,
                "description": page.description,
                "source": page.source,
                "headings": page.headings[:60],
                "total_chars": len(page.body),
                "truncated": len(text) < len(page.body),
            },
        }
    )


def _validate_transport(transport: str, host: str, *, allow_public: bool = False) -> None:
    """Binding beyond loopback is deliberate, never accidental.

    The server has no client authentication, so exposing it publishes the tools
    to whoever finds the URL. That is acceptable for this one — it serves public
    documentation and nothing else — but it has to be asked for by name.
    """
    if transport == "stdio" or host.lower() in LOOPBACK_HOSTS or allow_public:
        return
    raise RuntimeError(
        f"refusing to bind {transport} to {host}: this server has no client "
        "authentication. Use 127.0.0.1, or set HERMES_DOCS_MCP_ALLOW_PUBLIC_BIND=1 "
        "if serving the public docs to anyone with the URL is what you want."
    )


def run() -> None:
    transport = os.environ.get("HERMES_DOCS_MCP_TRANSPORT", "stdio")
    _validate_transport(
        transport, _HOST, allow_public=bool_env("HERMES_DOCS_MCP_ALLOW_PUBLIC_BIND")
    )
    if transport != "stdio":
        # Pull the docs before the port opens: a hosted instance should not spend
        # its first request downloading 5 MB, and a broken fetch belongs in the
        # deploy log rather than in someone's first search.
        anyio.run(ensure_cached, _STORE.cfg)
    mcp.run(transport=transport)
