#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${EDGARS_MCP_CHECK_URL:-http://127.0.0.1:8765}"
TOKEN="${MCP_API_TOKEN:-}"

command -v curl >/dev/null 2>&1 || { echo "edgars-mcp: curl is required." >&2; exit 1; }
if [[ -z "$TOKEN" ]]; then
  echo "edgars-mcp: MCP_API_TOKEN is missing; run this check through op run." >&2
  exit 1
fi

curl --fail --silent --show-error "$BASE_URL/health" >/dev/null
payload='{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
response="$(curl --fail --silent --show-error \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data "$payload" \
  "$BASE_URL/mcp")"

python3 -c 'import json,sys; p=json.load(sys.stdin); tools=p["result"]["tools"]; assert len(tools)==78, len(tools); names={t["name"] for t in tools}; assert {"warp_agent_runs_list","warp_agent_run_status","warp_agent_run_create"} <= names; print("PASS: health, 78 tools, Warp Oz tools")' <<<"$response"

