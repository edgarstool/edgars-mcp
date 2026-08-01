# ECS foundation comparison

This report is the only active-tree record of pre-convergence names. Git history remains the complete source of historical detail.

| Before | After | Outcome |
|---|---|---|
| `mcp-handcraft`, `handcraft-mcp`, `handcraft-http` | `edgars-mcp` | One project and runtime identity |
| Root `server_http.py` and scattered scripts | `src/edgars_mcp/` plus packaged entry points | Importable, testable package |
| `Handcraft-McpCommon` and `Start-HandcraftStack` wrappers | `deploy/linux/` and `deploy/windows/` | Platform-specific first-class deployment |
| `G:\AI_WORK_512` and `V:\projects` assumptions | `$HOME` defaults plus environment overrides | Linux and Windows portability |
| Doppler-required launch chain | 1Password CLI references | One cloud secret workflow |
| Mutable state inside or beside source | `~/runtime/edgars-mcp/{run,state,logs,cache,tmp}` | Source/runtime separation |
| Windows-only `cmd.exe`, PowerShell and drive enumeration | Native OS command construction | Contabo-compatible system tools |
| Separate Warp bridge proposal | Existing `warp_agent_*` MCP tools | Warp stays inside Edgar's MCP toolbox |

## Preserved contract

- Exactly 78 MCP tools remain registered.
- Existing tool names and input schemas remain unchanged.
- Warp keeps `warp_agent_runs_list`, `warp_agent_run_status`, and `warp_agent_run_create`.
- The service still exposes `/health` and `/mcp` on port 8765.

## Deployment boundary

This branch provides deployment-ready artifacts but does not alter live Contabo, Cloudflare, or DNS by itself. Live status must only be marked complete after the remote service check returns `PASS`.

