#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "Usage: $0 /path/to/1password-credentials.json /path/to/edgars-mcp.token" >&2
  exit 2
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
CONFIG_DIR="${EDGARS_MCP_CONFIG_DIR:-$HOME/.config/edgars-mcp}"
RUNTIME_DIR="${EDGARS_MCP_RUNTIME_DIR:-$HOME/runtime/edgars-mcp}"
OP_ENV_FILE="$CONFIG_DIR/edgars-mcp.op.env"
COMPOSE_FILE="$REPO_DIR/deploy/docker/compose.yaml"

command -v docker >/dev/null 2>&1 || {
  echo "edgars-mcp: Docker with Compose is required." >&2
  exit 1
}

bash "$REPO_DIR/deploy/linux/install-connect.sh" "$1" "$2"

install -d -m 0700 "$CONFIG_DIR"
mkdir -p "$RUNTIME_DIR"/{run,state,logs,cache,tmp}
chmod 0700 "$RUNTIME_DIR" "$RUNTIME_DIR"/{run,state,logs,cache,tmp}

if [[ ! -e "$OP_ENV_FILE" ]]; then
  install -m 0600 "$REPO_DIR/config/edgars-mcp.op.env.example" "$OP_ENV_FILE"
else
  chmod 0600 "$OP_ENV_FILE"
fi

docker compose -f "$COMPOSE_FILE" up -d --build

echo "Edgar's MCP and 1Password Connect stack started."
echo "Run: docker compose -f $COMPOSE_FILE ps"
