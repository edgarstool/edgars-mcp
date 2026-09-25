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
- Canonical restart-stable generic MCP surface: **288 tools** (fresh runtime baseline after `fleet_route`)

Supported startup chain:

```text
Windows Scheduled Task
  -> start-handcraft-http-at-login.ps1
  -> start-mcp.ps1
  -> server_http.py :8765
```

## Retired architecture

The legacy secret-runner/bootstrap launchers, container bootstrap, and retired batch launchers are removed and are not fallbacks.

## Canonical 288-tool profile

`start-mcp.ps1` explicitly enables Playwright, Kapture, Windows-MCP, Desktop Commander, OpenMontage, Hermes, OpenClaw, and Fleet wrappers. It explicitly disables Descope, cloudflared, and 1Password Connect wrappers inside edgars-mcp. `MCP_WRAP_ALL` stays off.

### Live inventory baseline

The generic tool surface is source-accounted and restart-verified. With `fleet_route` added, a fresh Kapture bridge exposes 31 tools, yielding the canonical 288-tool profile:

| Layer | Source | Tools |
| --- | --- | ---: |
| Base | `server_http.py` base surface | 67 |
| Native wrapper | wrapper catalog + OpenMontage + Hermes + OpenClaw + Fleet | 121 |
| MCP upstream bridge | Playwright 25 + Windows-MCP 18 + Desktop Commander 26 + Kapture 31 | 100 |
| Optional upstream | generic Honcho bridge | 0 |
| **Total generic MCP surface** |  | **288** |

All exposed names are unique under both exact and case-insensitive comparison. The earlier 289 snapshot came from a pre-restart Kapture bridge session that still exposed `kapture__evaluate`; fresh bridge connections and a restarted aggregate runtime expose 31 Kapture tools without `evaluate`. Treat 288 as the restart-stable acceptance baseline.

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

## Fleet auto routing

fleet_route(task_type) is a read-only route decision. It takes a fresh health snapshot for all existing fleet targets, checks live worker CPU/memory/disk telemetry where available, applies the bounded cost guard, and reports every candidate, selected target, and reason. It neither creates cloud resources nor dispatches work.

fleet_dispatch(target="auto", task_type=..., message=...) immediately repeats that route decision and sends the bounded text message only to the selected existing worker. Its schema deliberately exposes no command, args, shell, or argv, and its MCP result redacts the local dispatcher argv.

| task_type | Ordered preference | Capacity policy |
| --- | --- | --- |
| event | Azure → OVH MAIN → Kamatera → OVH SIDECAR | Azure's dedicated event health contract; SSH fallbacks need ≥1 CPU, 512 MB RAM, 1 GB free disk |
| website-audit | OVH MAIN → Kamatera → OVH SIDECAR | ≥4 CPU, 4 GB RAM, 10 GB free disk |
| general | OVH MAIN → Kamatera → OVH SIDECAR | ≥4 CPU, 4 GB RAM, 10 GB free disk |
| lightweight | OVH SIDECAR → OVH MAIN → Kamatera | ≥1 CPU, 512 MB RAM, 1 GB free disk |

EDGAR_FLEET_OVH_FREE_TRIAL_EXPIRES_AT is a non-secret, finite UTC cut-off supplied by start-mcp.ps1. While it is in the future, OVH candidates are eligible in their policy order. If it is absent, invalid, or elapsed, automatic routing excludes OVH instead of silently treating it as perpetual free capacity; it falls back to another healthy compatible worker. This is a bounded routing guard, not a live billing/credit API, so update the cut-off only after provider billing has been independently rechecked.

## Acceptance

```powershell
Invoke-WebRequest http://127.0.0.1:8765/health -UseBasicParsing
hermes mcp test edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\status-wrap.ps1
```

Accepted state: local health returns 200, `hermes mcp test edgars-mcp` discovers **288 generic tools**, `status-wrap.ps1` validates the exact restart-stable count, MCP `tools/list` contains no `linear_*` tools, `/linear/oauth/*` returns 404, and no active startup/docs path uses the retired Linear or secret-runner/bootstrap architecture.
