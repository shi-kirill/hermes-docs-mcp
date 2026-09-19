#!/usr/bin/env bash
# Register this server in Claude Desktop's config.
#
# Claude Desktop keeps its own copy of claude_desktop_config.json in memory and
# rewrites the file while it runs, silently dropping entries added behind its
# back. Run this with Claude fully quit (Cmd+Q), then start Claude.
#
# Idempotent: re-running only refreshes the command path.

set -euo pipefail

CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
NAME="hermes-docs"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$REPO/.venv/bin/hermes-docs-mcp"

[ -x "$BIN" ] || { echo "error: $BIN is missing or not executable. Run 'uv sync' first." >&2; exit 1; }

if pgrep -x Claude >/dev/null 2>&1; then
  echo "warning: Claude is running. It may overwrite this change on quit." >&2
  echo "         Quit Claude (Cmd+Q) and run this script again." >&2
fi

mkdir -p "$(dirname "$CONFIG")"
[ -f "$CONFIG" ] || echo '{}' > "$CONFIG"
cp "$CONFIG" "$CONFIG.bak-$(date +%Y%m%d-%H%M%S)"

CONFIG="$CONFIG" NAME="$NAME" BIN="$BIN" python3 - <<'PY'
import json, os, pathlib

path = pathlib.Path(os.environ["CONFIG"])
name, binary = os.environ["NAME"], os.environ["BIN"]
config = json.loads(path.read_text() or "{}")
config.setdefault("mcpServers", {})[name] = {"command": binary, "args": []}
tmp = path.with_suffix(".json.tmp")
tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n")
tmp.replace(path)
print(f"{name} registered. Servers now: {', '.join(config['mcpServers'])}")
PY

echo "Start Claude and look for $NAME among its MCP servers."
