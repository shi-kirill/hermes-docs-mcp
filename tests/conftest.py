"""Fixtures: a miniature docs corpus shaped exactly like the real exports."""

from __future__ import annotations

import http.server
import threading

import pytest

from hermes_docs_mcp.config import Config

BASE_URL = "https://docs.example.test"

FULL_TEXT = """# Hermes Agent — Full Documentation
This file is the entire documentation concatenated for LLM context ingestion.

---

<!-- source: website/docs/getting-started/installation.md -->
# Installation

# Installation

Get Hermes Agent running in under two minutes.

## Quick Install

Run the install script on Linux, macOS or WSL2.

```bash
curl -fsSL https://example.test/install.sh | bash
```

### Requirements

Node 20 or newer is required.

---

<!-- source: website/docs/user-guide/features/mcp.md -->
# MCP (Model Context Protocol)

MCP lets Hermes connect to external tool servers.

## Quick start

Add a server with `hermes mcp add`, then restart the agent. The command writes
an entry into the `mcp_servers` block of `~/.hermes/config.yaml`, where each
entry names a command, its arguments and any environment variables the server
needs. Stdio servers are launched as child processes; remote servers are reached
over SSE or streamable HTTP and must be given an explicit URL. Once the agent
restarts, `hermes mcp list` shows every configured server together with the
tools it exposes, and `hermes tools` narrows that set down to the tools you
actually want the model to see.

## Trust model

An MCP server runs with your privileges. Review the manifest before install.

---

<!-- source: website/docs/user-guide/messaging/index.md -->
# Messaging Platforms

The gateway speaks Telegram, Discord and Slack.

## Supported platforms

Telegram needs a bot token from BotFather.

---

<!-- source: website/docs/user-stories.mdx -->
# User Stories

How people run Hermes day to day.
"""

INDEX_TEXT = """# Hermes Agent

> The self-improving AI agent.

## Getting Started

- [Installation](https://docs.example.test/docs/getting-started/installation): Install on Linux, macOS, WSL2
- [Quickstart](https://docs.example.test/docs/getting-started/quickstart): First conversation

## Features

- [MCP Integration](https://docs.example.test/docs/user-guide/features/mcp): Connect Hermes to MCP servers
- [Messaging](https://docs.example.test/docs/user-guide/messaging/): Telegram, Discord, Slack
"""


@pytest.fixture
def full_text() -> str:
    return FULL_TEXT


@pytest.fixture
def index_text() -> str:
    return INDEX_TEXT


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(
        base_url=BASE_URL,
        cache_dir=tmp_path / "cache",
        ttl_seconds=3600,
        timeout=5.0,
        offline=False,
        min_refresh_seconds=0,
    )


@pytest.fixture
def seeded_cfg(cfg: Config) -> Config:
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    (cfg.cache_dir / "llms-full.txt").write_text(FULL_TEXT, encoding="utf-8")
    (cfg.cache_dir / "docs-llms.txt").write_text(INDEX_TEXT, encoding="utf-8")
    return cfg


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
