# hermes-docs-mcp

Локальный MCP-сервер, который даёт агенту полнотекстовый поиск и чтение
документации **Hermes Agent** (`hermes-agent.nousresearch.com/docs`) — офлайн,
из локального кэша, без скрейпинга сайта.

## Откуда берутся данные

Сайт документации сам публикует машиночитаемые выгрузки — ровно для того, чтобы
их скармливали языковым моделям:

| Файл | Что это | Размер |
|---|---|---|
| `/llms-full.txt` | вся документация одним markdown-файлом, страницы размечены маркерами `<!-- source: website/docs/….md -->` | ~4.9 МБ, 228 страниц |
| `/docs/llms.txt` | индекс всех страниц по разделам: заголовок, канонический URL, однострочное описание | ~43 КБ |

Сервер скачивает эти два файла (условными запросами по `ETag`/`Last-Modified`),
кладёт в кэш, разбирает на страницы и фрагменты по заголовкам и строит BM25-индекс
в памяти. Никакого парсинга HTML, приватных эндпоинтов и обхода защит: только
официальный экспорт, документация под MIT.

Текст, который возвращают инструменты, — это сторонняя документация. Для агента
это **данные для чтения, а не инструкции к исполнению**.

## Инструменты

| Инструмент | Назначение |
|---|---|
| `hermes_docs_search(query, limit, section, page)` | поиск по всей документации; возвращает ранжированные фрагменты с заголовком, разделом, сниппетом и ссылкой с якорем |
| `hermes_docs_page(page, heading, max_chars, offset)` | полный markdown страницы (или одного её раздела) с постраничной догрузкой через `next_offset` |
| `hermes_docs_list(section, query, limit)` | оглавление: страницы с однострочными описаниями, список разделов |
| `hermes_docs_refresh(force)` | обновить кэш и пересобрать индекс |
| `hermes_docs_status()` | состояние кэша и конфигурации; сеть не трогает |

`page` принимает путь (`user-guide/features/mcp`), полный URL документации или
точный заголовок страницы. `section` — как путь (`user-guide`, `developer-guide`,
`guides`, `reference`, `getting-started`, `integrations`), так и имя раздела
навигации (`Features`, `Using Hermes`, …).

## Установка

```bash
cd hermes-docs-mcp
uv sync
uv run hermes-docs-mcp   # stdio
```

Первый вызов любого инструмента, которому нужна документация, скачает выгрузки
(~5 МБ). Дальше всё работает из кэша; сеть нужна только при обновлении.

## Подключение

### Claude Code

```bash
claude mcp add hermes-docs -- uv --directory /полный/путь/hermes-docs-mcp run hermes-docs-mcp
```

### Hermes Agent

В `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  hermes-docs:
    command: uv
    args: ["--directory", "/opt/hermes-docs-mcp", "run", "hermes-docs-mcp"]
```

Агент, который умеет искать по собственной документации, сам находит нужные флаги,
ключи конфигурации и форматы `SOUL.md` вместо того, чтобы угадывать их.

## Настройки (переменные окружения)

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `HERMES_DOCS_MCP_BASE_URL` | `https://hermes-agent.nousresearch.com` | источник выгрузок; только https (http — лишь для loopback) |
| `HERMES_DOCS_MCP_CACHE_DIR` | `~/.cache/hermes-docs-mcp` | где лежит кэш; можно подсунуть заранее заполненный каталог |
| `HERMES_DOCS_MCP_TTL` | `86400` | через сколько секунд кэш считается устаревшим |
| `HERMES_DOCS_MCP_TIMEOUT` | `30` | таймаут HTTP, секунды |
| `HERMES_DOCS_MCP_OFFLINE` | не задана | `1` — никогда не ходить в сеть, работать только из кэша |
| `HERMES_DOCS_MCP_TRANSPORT` | `stdio` | `stdio`, `sse` или `streamable-http` |
| `HERMES_DOCS_MCP_HOST` / `_PORT` | `127.0.0.1` / `8020` | только для HTTP-транспортов |

HTTP-транспорты разрешены только на loopback: у сервера нет аутентификации
клиентов, наружу его выставлять нельзя.

### Полностью офлайн (например, закрытый VPS)

```bash
mkdir -p /opt/hermes-docs-cache
curl -fsSL -o /opt/hermes-docs-cache/llms-full.txt  https://hermes-agent.nousresearch.com/llms-full.txt
curl -fsSL -o /opt/hermes-docs-cache/docs-llms.txt  https://hermes-agent.nousresearch.com/docs/llms.txt
export HERMES_DOCS_MCP_CACHE_DIR=/opt/hermes-docs-cache HERMES_DOCS_MCP_OFFLINE=1
```

## Разработка

```bash
uv run pytest -q
uv run ruff check .
```

Тесты работают на локальных фикстурах и поднятом на loopback HTTP-сервере;
сеть для них не нужна. Отдельная проверка по «живому» сайту включается флагом
`HERMES_DOCS_MCP_LIVE=1`.

## Лицензия

MIT (код сервера). Сама документация Hermes Agent принадлежит Nous Research и
распространяется по условиям их репозитория (MIT). Проект неофициальный.
