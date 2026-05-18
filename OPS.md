# mcp-handcraft OPS

## Hermes stdio proxy

Use `hermes_stdio_proxy.py` when Hermes needs a stdio MCP command but the handcraft MCP service is running through `server_http.py`.

1. Start the HTTP server:

```powershell
.\run_http.cmd
```

2. Configure Hermes to launch:

```powershell
python .\hermes_stdio_proxy.py
```

3. Override the target endpoint only when needed:

```powershell
$env:HERMES_HANDCRAFT_MCP_URL = "https://mcp.whoasked.vip/mcp"
```

Keep runtime artifacts out of commits: `hermes_handcraft_http.log`, `.screenshots/`, `__pycache__/`, and generated images.

## Review scope

WHO-159 review includes both paths:

- Hermes stdio MCP initialize and `tools/list` through `hermes_stdio_proxy.py`.
- The MCP HTTP endpoint: `POST /mcp`, currently handled by `server_http.py`.
- The Discord webhook URL: `https://mcp.whoasked.vip/webhook/discord`.
- The package webhook URL for TrackTW: `https://mcp.whoasked.vip/webhook/package`.

Do not collapse these into one URL during review. `/mcp` is the MCP endpoint; `/webhook/discord` and `/webhook/package` are separate webhook entrypoints and must be checked separately.

## Package webhook

Use this when a package or TrackTW integration asks for a webhook URL:

```text
https://mcp.whoasked.vip/webhook/package
```

Local test endpoint:

```powershell
curl.exe -X POST http://127.0.0.1:8765/webhook/package -H "Content-Type: application/json" -d "{\"tracking_number\":\"TEST123\"}"
```
