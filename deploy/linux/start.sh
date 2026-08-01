#!/usr/bin/env bash
set -euo pipefail

SOURCE_DIR="${EDGARS_MCP_SOURCE_DIR:-$HOME/workspaces/shared/30-services/edgars-mcp}"
CONFIG_DIR="${EDGARS_MCP_CONFIG_DIR:-$HOME/.config/edgars-mcp}"
OP_ENV_FILE="${EDGARS_MCP_OP_ENV_FILE:-$CONFIG_DIR/edgars-mcp.op.env}"
PYTHON_BIN="${EDGARS_MCP_PYTHON:-$SOURCE_DIR/.venv/bin/python}"

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

credential_file="${CREDENTIALS_DIRECTORY:-}/op-service-account-token"
if [[ -z "${OP_SERVICE_ACCOUNT_TOKEN:-}" && -r "$credential_file" ]]; then
  export OP_SERVICE_ACCOUNT_TOKEN
  OP_SERVICE_ACCOUNT_TOKEN="$(<"$credential_file")"
fi

if ! op whoami >/dev/null 2>&1; then
  echo "edgars-mcp: 1Password CLI is not authenticated." >&2
  echo "Provide an encrypted systemd credential or authenticate op before starting." >&2
  exit 1
fi

cd "$SOURCE_DIR"
exec op run --env-file "$OP_ENV_FILE" -- "$PYTHON_BIN" -m edgars_mcp.http_server

