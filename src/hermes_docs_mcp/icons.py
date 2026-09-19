"""The server's icon, offered in two forms.

MCP hands clients a list of icons in the initialize response and lets them pick.
A hosted instance can point at a URL it serves itself, which keeps the handshake
small; a stdio one has no URL at all, so it inlines a small data URI instead.
Offering both means neither transport is left without a logo.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path

from mcp.types import Icon

ASSETS = Path(__file__).parent / "assets"
LARGE = "icon-128.png"
SMALL = "icon-48.png"
ICON_ROUTE = f"/{LARGE}"


@lru_cache(maxsize=2)
def data_uri(name: str) -> str:
    """Empty when the asset is missing: a lost logo must not stop the server."""
    try:
        encoded = base64.b64encode((ASSETS / name).read_bytes()).decode("ascii")
    except OSError:
        return ""
    return f"data:image/png;base64,{encoded}"


def public_base_url() -> str:
    """Absolute origin of a hosted instance, if it knows one."""
    return os.environ.get("HERMES_DOCS_MCP_PUBLIC_URL", "").strip().rstrip("/")


def server_icons() -> list[Icon]:
    icons: list[Icon] = []
    base = public_base_url()
    if base:
        icons.append(Icon(src=f"{base}{ICON_ROUTE}", mimeType="image/png", sizes=["128x128"]))
    inline = data_uri(SMALL)
    if inline:
        icons.append(Icon(src=inline, mimeType="image/png", sizes=["48x48"]))
    return icons
