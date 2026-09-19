"""Fixtures: a miniature docs corpus shaped exactly like the real exports."""

from __future__ import annotations

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
    )


@pytest.fixture
def seeded_cfg(cfg: Config) -> Config:
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    (cfg.cache_dir / "llms-full.txt").write_text(FULL_TEXT, encoding="utf-8")
    (cfg.cache_dir / "docs-llms.txt").write_text(INDEX_TEXT, encoding="utf-8")
    return cfg
