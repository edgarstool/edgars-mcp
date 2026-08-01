#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${EDGARS_MCP_SOURCE_DIR:-$HOME/workspaces/shared/30-services/edgars-mcp}"
CONFIG_DIR="${EDGARS_MCP_CONFIG_DIR:-$HOME/.config/edgars-mcp}"
OP_ENV_FILE="${EDGARS_MCP_OP_ENV_FILE:-$CONFIG_DIR/edgars-mcp.op.env}"
PYTHON_BIN="${EDGARS_MCP_PYTHON:-$SOURCE_DIR/.venv/bin/python}"
OP_CONNECT_HOST="${OP_CONNECT_HOST:-http://127.0.0.1:8080}"

if ! command -v op >/dev/null 2>&1; then
  echo "edgars-mcp: 1Password CLI (op) is required." >&2
  exit 1
fi

if [[ ! -r "$OP_ENV_FILE" ]]; then
  echo "edgars-mcp: missing 1Password reference file: $OP_ENV_FILE" >&2
  exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "edgars-mcp: Python environment is missing; run deploy/linux/install.sh first." >&2
  exit 1
fi

credential_file="${OP_CONNECT_TOKEN_FILE:-}"
if [[ -z "$credential_file" && -n "${CREDENTIALS_DIRECTORY:-}" ]]; then
  credential_file="$CREDENTIALS_DIRECTORY/op-connect-token"
fi
credential_file="${credential_file:-$HOME/.config/1password-connect/edgars-mcp.token}"
if [[ -z "${OP_CONNECT_TOKEN:-}" && -r "$credential_file" ]]; then
  export OP_CONNECT_TOKEN
  OP_CONNECT_TOKEN="$(tr -d '\r\n' < "$credential_file")"
fi
if [[ -z "${OP_CONNECT_TOKEN:-}" ]]; then
  echo "edgars-mcp: 1Password Connect token is missing." >&2
  exit 1
fi
export OP_CONNECT_HOST
unset OP_SERVICE_ACCOUNT_TOKEN || true

if ! op whoami >/dev/null 2>&1; then
  echo "edgars-mcp: 1Password CLI could not authenticate through Connect at $OP_CONNECT_HOST." >&2
  exit 1
fi

cd "$SOURCE_DIR"
exec op run --env-file "$OP_ENV_FILE" -- "$PYTHON_BIN" -m edgars_mcp.http_server
