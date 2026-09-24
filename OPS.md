# edgars-mcp v2.0.0 — Operations

## Single source of truth

Runtime architecture is Windows-native. Repo `master` is the code source of truth; Windows Scheduled Task `edgars-mcp-http` is the startup source of truth.

```text
edgars-mcp-http
  -> wscript.exe scripts\Start_Handcraft_MCP_HTTP.vbs
  -> start-handcraft-http-at-login.ps1
  -> start-mcp.ps1
  -> server_http.py :8765
```

The login starter hydrates Process environment from Windows Machine/User scope before launching the server.

## Canonical profile

Expected generic MCP surface: **284–285 tools**. Breakdown: base 67; native wrappers 117 (catalog 1, OpenMontage 106, Hermes 5, OpenClaw 5); bridged upstreams 100–101 (Playwright 25, Windows-MCP 18, Desktop Commander 26, Kapture 31–32); optional generic Honcho upstream 0. Kapture may dynamically advertise `evaluate`, so 284 and 285 are both accepted for this profile. `MCP_WRAP_ALL` is off. Product/agent wrappers are individually enabled; Descope/cloudflared/1Password-Connect wrappers are individually disabled. Self-hosted Honcho is an identity-gated REST/memory plane and is not counted as a generic MCP upstream.

## Health

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File V:\projects\edgars-mcp\scripts\check-mcp.ps1
```

Local acceptance: TCP 8765 listening, `/health` HTTP 200, MCP handshake succeeds, Python available, and the public edge is reachable when Cloudflare is expected online. Port 8765 is MCP-only; legacy `/webhook/*` and `/webhooks/*` receiver paths must return 404.

## Maintenance

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File V:\projects\edgars-mcp\scripts\maintain-mcp.ps1 -RestartIfUnhealthy
```

Maintenance checks Python/cloudflared, rotates logs, validates health, and can run unit tests. It does not validate or invoke the retired secret bootstrap.

## Retired — do not restore

- legacy secret-runner/bootstrap launch paths
- external secret-manager project bootstrap
- Docker/WSL/bootstrap dependency for edgars-mcp
- `run*.cmd` launchers
- `Start-HandcraftStack.ps1`
- backup copies of those launchers as supported fallbacks

## Release acceptance

1. Python syntax compile passes.
2. Focused tests pass; Windows-only live assertions may be skipped on non-Windows CI.
3. Active runtime/docs scan finds zero retired launch references.
4. Windows live verification returns health 200 and 284–285 tools via both local `tools/list` and `hermes mcp test edgars-mcp`; tool names have no exact or case-insensitive collision.
