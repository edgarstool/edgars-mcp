# honcho-mcp-facade

Cloudflare Worker facade for Honcho's hosted remote MCP server.

Purpose:

```text
Cloudflare MCP Portal
→ https://honcho.edgars.tools/mcp
→ this Worker
→ https://mcp.honcho.dev
```

This exists because Honcho MCP requires multiple upstream headers:

```text
Authorization: Bearer <HONCHO_API_KEY>
X-Honcho-User-Name: <user>
X-Honcho-Workspace-ID: <workspace>
X-Honcho-Assistant-Name: <assistant>
```

Cloudflare AI Controls MCP server header auth can be awkward for multi-header upstreams, and one observed `honcho` entry failed with:

```text
Invalid header name.
```

Current production note:

```text
Primary portal path:
entry.edgars.tools/mcp
→ honcho
→ https://honcho-mcp.edgars.tools/mcp
→ edgars-mcp server_http.py facade
→ https://mcp.honcho.dev
```

This Worker is a deployable fallback. Direct curl verification against `https://honcho.edgars.tools/mcp` worked, but Cloudflare AI Controls sync did not reach the Worker during the first test and returned `unable to connect to server`. Prefer the tunnel/origin facade until that Cloudflare control-plane behavior is resolved.

## Required Secrets

Set these as Worker secrets, not repo files:

```powershell
cd V:\projects\edgars-mcp\cloudflare\workers\honcho-mcp-facade

npx wrangler secret put HONCHO_API_KEY
npx wrangler secret put EDGARS_HONCHO_MCP_FACADE_TOKEN
```

Optional:

```powershell
npx wrangler secret put HONCHO_USER_NAME
npx wrangler secret put HONCHO_WORKSPACE_ID
npx wrangler secret put HONCHO_ASSISTANT_NAME
```

Defaults:

```text
HONCHO_USER_NAME=Edgar
HONCHO_WORKSPACE_ID=edgar-team
HONCHO_ASSISTANT_NAME=codex
```

## Deploy

```powershell
cd V:\projects\edgars-mcp\cloudflare\workers\honcho-mcp-facade
npx wrangler deploy
```

## Cloudflare AI Controls

Create or replace the broken `honcho` MCP server with:

```text
Name: honcho
Server ID: honcho
HTTP URL: https://honcho.edgars.tools/mcp
Authentication: header-based / bearer
Header name: Authorization
Header value: Bearer <EDGARS_HONCHO_MCP_FACADE_TOKEN>
Require user auth: off / on_behalf=false
```

Then add it to:

```text
Portal: edgars-entry
URL: https://entry.edgars.tools/mcp
```

## Verify

No token should be rejected:

```powershell
curl.exe -i https://honcho.edgars.tools/mcp
```

Health should work:

```powershell
curl.exe -i https://honcho.edgars.tools/health
```

With `EDGARS_HONCHO_MCP_FACADE_TOKEN`, a direct MCP `tools/list` call should reach Honcho and list tools. Cloudflare AI Controls sync may still need Dashboard-side server credential repair before this Worker can be used as the registered upstream.
