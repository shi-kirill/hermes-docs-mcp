#!/usr/bin/env bash
# Install this server for Claude Desktop.
#
# Two macOS facts drive this script:
#
# 1. Claude launches MCP servers without access to ~/Desktop, ~/Documents or
#    ~/Downloads. A venv living there dies before Python starts:
#    "PermissionError: Operation not permitted: .../.venv/pyvenv.cfg".
#    So the runtime is installed outside those folders, while the repository
#    can stay wherever you keep it.
# 2. Claude Desktop keeps claude_desktop_config.json in memory and rewrites it
#    while running, silently dropping entries added behind its back. Run this
#    with Claude fully quit (Cmd+Q), then start Claude.
#
# Idempotent: re-run after changing the code to reinstall and re-register.

set -euo pipefail

NAME="hermes-docs"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PREFIX="${HERMES_DOCS_MCP_PREFIX:-$HOME/hermes-docs-mcp}"
CONFIG="$HOME/Library/Application Support/Claude/claude_desktop_config.json"
BIN="$PREFIX/.venv/bin/hermes-docs-mcp"

case "$PREFIX/" in
  "$HOME"/Desktop/*|"$HOME"/Documents/*|"$HOME"/Downloads/*)
    echo "error: $PREFIX is inside a folder macOS hides from Claude." >&2
    echo "       Pick another one: HERMES_DOCS_MCP_PREFIX=~/hermes-docs-mcp $0" >&2
    exit 1 ;;
esac

UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
[ -x "$UV" ] || { echo "error: uv not found. See https://docs.astral.sh/uv/" >&2; exit 1; }

if ps -Ao comm= | sed "s|.*/||" | grep -qx Claude; then
  echo "warning: Claude is running and will overwrite this change within seconds." >&2
  echo "         Quit Claude (Cmd+Q) and run this script again." >&2
fi

echo "Building $REPO -> $PREFIX"
"$UV" build --wheel --project "$REPO" --out-dir "$REPO/dist" >/dev/null
WHEEL="$(ls -t "$REPO"/dist/*.whl | head -1)"
[ -x "$PREFIX/.venv/bin/python" ] || "$UV" venv "$PREFIX/.venv" --python 3.12 >/dev/null
"$UV" pip install --quiet --python "$PREFIX/.venv/bin/python" --reinstall "$WHEEL"
[ -x "$BIN" ] || { echo "error: $BIN was not installed" >&2; exit 1; }

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
print(f"{name} -> {binary}")
print("servers now:", ", ".join(config["mcpServers"]))
PY

echo "Start Claude and look for $NAME among its MCP servers."
