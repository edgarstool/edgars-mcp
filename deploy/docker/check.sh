#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${EDGARS_MCP_CHECK_URL:-http://127.0.0.1:8765}"
OP_CONNECT_HOST="${OP_CONNECT_HOST:-http://op-connect-api:8080}"
OP_CONNECT_TOKEN_FILE="${OP_CONNECT_TOKEN_FILE:-/run/secrets/op_connect_token}"
OP_ENV_FILE="${EDGARS_MCP_OP_ENV_FILE:-/etc/edgars-mcp/edgars-mcp.op.env}"

if [[ ! -r "$OP_CONNECT_TOKEN_FILE" ]]; then
  echo "edgars-mcp: 1Password Connect token file is missing or unreadable." >&2
  exit 1
fi
if [[ ! -r "$OP_ENV_FILE" ]]; then
  echo "edgars-mcp: 1Password reference file is missing or unreadable." >&2
  exit 1
fi

export OP_CONNECT_HOST
export OP_CONNECT_TOKEN
OP_CONNECT_TOKEN="$(tr -d '\r\n' < "$OP_CONNECT_TOKEN_FILE")"
unset OP_SERVICE_ACCOUNT_TOKEN || true

exec op run --env-file "$OP_ENV_FILE" -- python - "$BASE_URL" <<'PY'
import json
import os
import sys
import urllib.request

base_url = sys.argv[1].rstrip("/")
with urllib.request.urlopen(f"{base_url}/health", timeout=5) as response:
    if not 200 <= response.status < 300:
        raise SystemExit(f"health returned HTTP {response.status}")

payload = json.dumps(
    {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
).encode("utf-8")
request = urllib.request.Request(
    f"{base_url}/mcp",
    data=payload,
    headers={
        "Authorization": f"Bearer {os.environ['MCP_API_TOKEN']}",
        "Content-Type": "application/json",
    },
    method="POST",
)
with urllib.request.urlopen(request, timeout=10) as response:
    result = json.load(response)

tools = result["result"]["tools"]
names = {tool["name"] for tool in tools}
warp_tools = {
    "warp_agent_runs_list",
    "warp_agent_run_status",
    "warp_agent_run_create",
}
if len(tools) != 78:
    raise SystemExit(f"expected 78 tools, received {len(tools)}")
if not warp_tools <= names:
    raise SystemExit(f"missing Warp tools: {sorted(warp_tools - names)}")

print("PASS: health, 78 tools, Warp Oz tools")
PY
