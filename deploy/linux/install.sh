#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${EDGARS_MCP_SOURCE_DIR:-$HOME/workspaces/shared/30-services/edgars-mcp}"
CONFIG_DIR="${EDGARS_MCP_CONFIG_DIR:-$HOME/.config/edgars-mcp}"
RUNTIME_DIR="${EDGARS_MCP_RUNTIME_DIR:-$HOME/runtime/edgars-mcp}"
UNIT_DIR="$HOME/.config/systemd/user"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"

if [[ "$REPO_DIR" != "$SOURCE_DIR" ]]; then
  echo "edgars-mcp: install from the canonical checkout at $SOURCE_DIR" >&2
  echo "Current checkout: $REPO_DIR" >&2
  exit 1
fi

command -v python3 >/dev/null 2>&1 || { echo "edgars-mcp: python3 is required." >&2; exit 1; }
command -v op >/dev/null 2>&1 || { echo "edgars-mcp: 1Password CLI (op) is required." >&2; exit 1; }

mkdir -p "$CONFIG_DIR" "$UNIT_DIR"
mkdir -p "$RUNTIME_DIR"/{run,state,logs,cache,tmp}
chmod 700 "$CONFIG_DIR" "$RUNTIME_DIR" "$RUNTIME_DIR"/{run,state,logs,cache,tmp}

python3 -m venv "$SOURCE_DIR/.venv"
"$SOURCE_DIR/.venv/bin/python" -m pip install --upgrade pip
"$SOURCE_DIR/.venv/bin/python" -m pip install -e "$SOURCE_DIR[all]"

if [[ ! -e "$CONFIG_DIR/edgars-mcp.env" ]]; then
  cp "$SOURCE_DIR/config/edgars-mcp.env.example" "$CONFIG_DIR/edgars-mcp.env"
fi
if [[ ! -e "$CONFIG_DIR/edgars-mcp.op.env" ]]; then
  cp "$SOURCE_DIR/config/edgars-mcp.op.env.example" "$CONFIG_DIR/edgars-mcp.op.env"
fi
chmod 600 "$CONFIG_DIR"/*.env

cp "$SOURCE_DIR/deploy/linux/edgars-mcp.service" "$UNIT_DIR/edgars-mcp.service"
systemctl --user daemon-reload
systemctl --user enable edgars-mcp.service

echo "edgars-mcp installed. Configure 1Password references, then run:"
echo "  deploy/linux/install-connect.sh /path/to/1password-credentials.json /path/to/edgars-mcp.token"
echo "  systemctl --user start edgars-mcp.service"
