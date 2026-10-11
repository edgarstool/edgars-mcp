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

Expected generic MCP surface: **384 tools**. Breakdown: base 71 (includes 7 `codex_*` tools); native wrappers 161 (catalog 1, OpenMontage 132, Hermes 13, OpenClaw 11, Fleet 4); bridged upstreams 152 (Playwright 25, Windows-MCP 18, Desktop Commander 26, Kapture 31, YouTrack 23, Chrome DevTools 29); optional generic Honcho upstream 0. `gemini_agent` and `claude_code_agent` are removed from the base surface. Linear is not advertised; YouTrack is the `yt__` bridge. Fresh Kapture bridge connections do not expose `evaluate`. `MCP_WRAP_ALL` is off. Product/agent wrappers are individually enabled, including YouTrack and Chrome DevTools. Descope/cloudflared/1Password-Connect wrappers stay individually disabled because their optional command/URL env is not configured. Self-hosted Honcho is an identity-gated REST/memory plane and is not counted as a generic MCP upstream.

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
4. Windows live verification returns health 200 and exactly 384 tools via both local `tools/list` and `hermes mcp test edgars-mcp`; tool names have no exact or case-insensitive collision.
