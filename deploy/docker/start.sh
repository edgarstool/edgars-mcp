#!/usr/bin/env bash
set -euo pipefail

OP_CONNECT_HOST="${OP_CONNECT_HOST:-http://op-connect-api:8080}"
OP_CONNECT_TOKEN_FILE="${OP_CONNECT_TOKEN_FILE:-/run/secrets/op_connect_token}"
OP_ENV_FILE="${EDGARS_MCP_OP_ENV_FILE:-/etc/edgars-mcp/edgars-mcp.op.env}"
CONNECT_WAIT_SECONDS="${EDGARS_MCP_CONNECT_WAIT_SECONDS:-60}"

if [[ ! -r "$OP_CONNECT_TOKEN_FILE" ]]; then
  echo "edgars-mcp: 1Password Connect token file is missing or unreadable: $OP_CONNECT_TOKEN_FILE" >&2
  exit 1
fi

command -v op >/dev/null 2>&1 || {
  echo "edgars-mcp: 1Password CLI (op) is required." >&2
  exit 1
}

if [[ ! -r "$OP_ENV_FILE" ]]; then
  echo "edgars-mcp: 1Password reference file is missing or unreadable: $OP_ENV_FILE" >&2
  exit 1
fi

export OP_CONNECT_HOST
export OP_CONNECT_TOKEN
OP_CONNECT_TOKEN="$(tr -d '\r\n' < "$OP_CONNECT_TOKEN_FILE")"
if [[ -z "$OP_CONNECT_TOKEN" ]]; then
  echo "edgars-mcp: 1Password Connect token file is empty." >&2
  exit 1
fi
unset OP_SERVICE_ACCOUNT_TOKEN || true

python - "$OP_CONNECT_HOST/health" "$CONNECT_WAIT_SECONDS" <<'PY'
import sys
import time
import urllib.error
import urllib.request

url = sys.argv[1]
timeout = float(sys.argv[2])
deadline = time.monotonic() + timeout
last_error = "not ready"

while time.monotonic() <= deadline:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if 200 <= response.status < 300:
                break
            last_error = f"HTTP {response.status}"
    except (OSError, urllib.error.URLError) as error:
        last_error = str(error)
    time.sleep(1)
else:
    raise SystemExit(f"edgars-mcp: 1Password Connect did not become healthy: {last_error}")
PY

exec op run --env-file "$OP_ENV_FILE" -- python -m edgars_mcp.http_server
