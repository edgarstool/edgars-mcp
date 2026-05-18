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

Do not collapse these into one URL during review. `/mcp` is the MCP endpoint; `/webhook/discord` is the webhook entrypoint and must be checked separately.
