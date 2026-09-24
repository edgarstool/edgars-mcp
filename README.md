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
- Canonical verified generic MCP surface: **253 tools**

Supported startup chain:

```text
Windows Scheduled Task
  -> start-handcraft-http-at-login.ps1
  -> start-mcp.ps1
  -> server_http.py :8765
```

## Retired architecture

The legacy secret-runner/bootstrap launchers, container bootstrap, and retired batch launchers are removed and are not fallbacks.

## Canonical 253-tool profile

`start-mcp.ps1` explicitly enables Playwright, Windows-MCP, Desktop Commander, OpenMontage, Hermes, and OpenClaw wrappers. It explicitly disables Descope, cloudflared, and 1Password Connect wrappers inside edgars-mcp. `MCP_WRAP_ALL` stays off.

Honcho is no longer counted as a generic 16-tool upstream. The current self-hosted `honcho.edgars.tools` service is an identity-gated REST/memory plane, not a generic MCP server. ChatGPT/Honcho access uses the dedicated `/chatgpt-honcho` contract; generic Honcho MCP proxying is opt-in only through an explicit `HONCHO_MCP_UPSTREAM_URL`.

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
mcporter list
```

Accepted state: local health returns `200`, `edgars-mcp` reports **253 generic tools**, MCP `tools/list` contains no `linear_*` tools, `/linear/oauth/*` returns `404`, and no active startup/docs path uses the retired Linear or secret-runner/bootstrap architecture.
