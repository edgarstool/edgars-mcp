# Contabo Deployment Convergence — 2026-08-06

## Result

The refactored Edgar’s MCP server is now running on Contabo as the production origin at `127.0.0.1:8765`.

- Image: `edgar/edgars-mcp-full:20260806-honcho`
- Base tool contract: 78 tools
- Honcho production exposure: disabled pending upstream repair
- Secrets: resolved through the existing self-hosted 1Password Connect API
- Public resource: `https://mcp.edgars.tools/mcp`

## Verified

- 1Password Connect API authenticated request: PASS
- Connect Sync restart and `sync complete`: PASS
- MCP initialization: PASS
- MCP tools/list: 78 tools
- Warp Oz three-tool contract: PASS
- Echo tool call: PASS
- Warp read-only run listing: PASS
- MCP restart and recovery: PASS
- Public protected-resource metadata: HTTP 200
- Public unauthenticated MCP request: HTTP 401
- Ports 18080, 8765, and 5678 remain loopback-only

## n8n

- Version: 2.32.7
- Health: PASS
- Encryption key configured: yes
- PostgreSQL backup: PASS
- Temporary PostgreSQL restore: PASS
- Smoke workflow import and execution: PASS
- Restart persistence and second execution: PASS

## Honcho status

The optional integrated proxy was ported into `src/edgars_mcp/http_server.py` and covered by focused tests. A candidate runtime successfully loaded 30 official Honcho tool descriptors, producing 108 total tools.

However, official Honcho MCP read-only calls currently return a tool error containing upstream HTTP 520. This was reproduced directly against `mcp.honcho.dev`, outside Edgar’s MCP. Production therefore omits `HONCHO_API_KEY` and keeps the stable 78-tool surface.

No new workspace, peer, or assistant was created. Existing identity remains `Edgar` / `edgar-team` / `hermes_default`.

## Git

- Honcho integration commit: `8c019415b379d249bb978a9a041b8bd9ae27ec8d`
- Remote branch: `refactor/ecs-foundation-v1`
- Tests: 156 passed with a temporary `python` → `python3` PATH shim
- Docker package build: PASS

## Recovery

Deployment checkpoint:
`/srv/edgar/backups/deployment-convergence-20260805T191021Z`

The checkpoint contains inventory, Compose snapshots, pre/post n8n backups, restore evidence, port/secret audit, Honcho blocker details, and rollback instructions. No plaintext credential values are recorded.
