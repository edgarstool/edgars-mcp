# Deploy — Edgar's Knowledge Streamable HTTP MCP

**Do not invent new paid infra.** Prefer $0 / existing edgars.tools edge.

Runtime artifact: `http_server.py` (stdlib; depends on sibling `server.py`).

Required env in prod:

- `PUBLIC_BASE_URL=https://<public-host>` (no trailing slash)
- Optional: `MCP_API_TOKEN` (ops canary only; leave unset for ChatGPT OAuth tokens)
- `EDGARS_KNOWLEDGE_API=https://knowledge-api.edgars.tools`
- `EDGARS_AUTH_SERVER=https://auth.edgars.tools`

---

## (a) Fix `mcp.edgars.tools` origin route — **preferred**

Today `https://mcp.edgars.tools/` responds via Cloudflare but does **not** serve this Streamable HTTP MCP (`/mcp` currently redirects oddly toward `/callback`).

Steps (existing CF + origin; $0 incremental):

1. Point the `mcp.edgars.tools` origin/worker/route at a process that runs:
   ```bash
   PUBLIC_BASE_URL=https://mcp.edgars.tools python3 http_server.py
   ```
   (or reverse-proxy `/mcp`, `/health`, `/.well-known/oauth-protected-resource*` to that process).
2. Ensure TLS stays on the existing Cloudflare zone.
3. Confirm ChatGPT fill-in URL: `https://mcp.edgars.tools/mcp`
4. Confirm:
   - `GET /health` → 200
   - `GET /.well-known/oauth-protected-resource/mcp` → JSON with `resource=https://mcp.edgars.tools`
   - unauthenticated `POST /mcp` → **401** + `WWW-Authenticate` `resource_metadata=…/mcp`

No new domain, no new billable product — fix routing only.

---

## (b) Cloudflare Worker / tunnel — **$0 if already on CF**

If the Python process cannot sit on the current origin:

- **Worker**: thin proxy Worker that forwards `/mcp`, `/health`, `/.well-known/*` to a free tunnel/`cloudflared` target running `http_server.py`, **or** re-implement the same handlers in a Worker that still calls `knowledge-api.edgars.tools` (keep logic equivalent; do not build a second KB).
- **Tunnel**: `cloudflared` from any always-on box already in the estate → hostname under `*.edgars.tools`.

Stay inside the existing Cloudflare plan; avoid paid Workers paid-tier upgrades unless already covered.

---

## (c) Vercel — **only if feasible / free tier**

Vercel Python serverless can host a WSGI/ASGI wrapper, but Streamable HTTP + long tool calls + OAuth discovery paths are awkward on short-lived functions.

Use only if:

- A free Hobby deployment already exists for edgars.tools work, and
- You wrap `http_server` behind an ASGI adapter **or** replace with a minimal FastAPI/Starlette port that preserves the same routes.

Otherwise skip Vercel; (a) or (b) are better fits for MCP Streamable HTTP.

---

## Out of scope / do not

- Do **not** deploy a second knowledge database or RAG stack.
- Do **not** add paid Redis/auth SaaS for this adapter.
- Do **not** point ChatGPT at `knowledge.edgars.tools` (known redirect loop) or invent a new public KB URL.

## Post-deploy canary (manual)

```bash
curl -sS https://mcp.edgars.tools/health
curl -sS https://mcp.edgars.tools/.well-known/oauth-protected-resource/mcp
curl -sS -D- -o /dev/null https://mcp.edgars.tools/mcp | head
# expect HTTP/2 401 and WWW-Authenticate with resource_metadata
```

Wire ChatGPT connector only after 401 + metadata look correct.
