# edgars-mcp v2.0.0

Windows-native MCP aggregation server for EDGAR-OS.

## Canonical runtime

- Repo: `V:\projects\edgars-mcp`
- HTTP: `http://127.0.0.1:8765/mcp`
- Health: `http://127.0.0.1:8765/health`

Port `8765` is MCP-only. Webhook/event ingress does **not** run in `server_http.py`; use the dedicated `hooks.edgars.tools` / Hermes event path instead.
- Public edge: `https://mcp.edgars.tools/mcp`
- Startup task: `edgars-mcp-http` -> `scripts\Start_Handcraft_MCP_HTTP.vbs`
- Runtime config/secrets: Windows Machine/User environment variables read directly by Python
- Canonical live-verified generic MCP surface: **284–285 tools** (source-dependent snapshot range, 2026-09-25)

Supported startup chain:

```text
Windows Scheduled Task
  -> start-handcraft-http-at-login.ps1
  -> start-mcp.ps1
  -> server_http.py :8765
```

## Retired architecture

The legacy secret-runner/bootstrap launchers, container bootstrap, and retired batch launchers are removed and are not fallbacks.

## Canonical 284–285-tool profile

`start-mcp.ps1` explicitly enables Playwright, Kapture, Windows-MCP, Desktop Commander, OpenMontage, Hermes, OpenClaw, and Fleet wrappers. It explicitly disables Descope, cloudflared, and 1Password Connect wrappers inside edgars-mcp. `MCP_WRAP_ALL` stays off.

### Live inventory baseline

The generic tool surface is source-accounted rather than pinned to one brittle total. On 2026-09-25 the same profile live-verified at 287 tools while Kapture exposed 31 bridge tools, and at 288 when Kapture dynamically advertised `evaluate` as a 32nd tool:

| Layer | Source | Tools |
| --- | --- | ---: |
| Base | `server_http.py` base surface | 67 |
| Native wrapper | wrapper catalog + OpenMontage + Hermes + OpenClaw + Fleet + Fleet | 120 |
| MCP upstream bridge | Playwright 25 + Windows-MCP 18 + Desktop Commander 26 + Kapture 31–32 | 100–101 |
| Optional upstream | generic Honcho bridge | 0 |
| **Total generic MCP surface** |  | **284–285** |

All exposed names are unique under both exact and case-insensitive comparison. Kapture can advertise `evaluate` dynamically, so an exact total of 287 versus 288 is not itself a regression; source availability, uniqueness, and the accepted 284–285 range are the stable acceptance criteria.

Honcho is not counted as a generic MCP upstream. The current self-hosted `honcho.edgars.tools` service is an identity-gated REST/memory plane, not a generic MCP server. ChatGPT/Honcho access uses the dedicated `/chatgpt-honcho` contract; generic Honcho MCP proxying is opt-in only through an explicit `HONCHO_MCP_UPSTREAM_URL`. Its independent health route is `https://honcho.edgars.tools/health`.

## Start / check / stop

```powershell
Set-Location V:\projects\edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-mcp.ps1
```

Cursor/stdio uses direct Python; see `config/mcp.local.example.json`. `stdio_proxy.py` reads `MCP_API_TOKEN` from the inherited Windows environment and proxies to the local HTTP server.

## Runtime variables

Set required values at Windows Machine or User scope. Common variables include `MCP_API_TOKEN`, `PERPLEXITY_API_KEY`, and provider-specific keys used by enabled tools. Secret values do not belong in this repo, scripts, logs, or command lines.

Linear integration was retired on 2026-09-22 after migration to YouTrack. Historical plugin/OAuth artifacts are preserved under `archive/retired-linear-20260922/` and are not active runtime inputs.

## Acceptance

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing
hermes mcp test edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\status-wrap.ps1
```

Accepted state: local health returns `200`, `hermes mcp test edgars-mcp` discovers **284–285 generic tools**, `status-wrap.ps1` validates that accepted range, MCP `tools/list` contains no `linear_*` tools, `/linear/oauth/*` returns `404`, and no active startup/docs path uses the retired Linear or secret-runner/bootstrap architecture.
