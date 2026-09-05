# ChatGPT connector — Edgar's Knowledge MCP

Remote **Streamable HTTP** MCP that proxies ChatGPT tools to the existing Knowledge API:

`https://knowledge-api.edgars.tools`

Not a new KB / RAG stack.

## Server URL (fill in ChatGPT UI)

| Field | Value |
|---|---|
| **Connector name** | Edgar's Knowledge |
| **MCP server URL** | `https://HOST/mcp` |
| **Transport** | Streamable HTTP |
| **Authentication** | OAuth |
| **Authorization server** | `https://auth.edgars.tools` (discovered via protected-resource metadata) |

Replace `HOST` with the public origin of this process (`PUBLIC_BASE_URL`, e.g. `https://mcp.edgars.tools`).

Example when origin is fixed:

```
https://mcp.edgars.tools/mcp
```

## Discovery / OAuth metadata (automatic)

ChatGPT should discover auth from:

- `GET /.well-known/oauth-protected-resource`
- `GET /.well-known/oauth-protected-resource/mcp`

Unauthenticated `POST/GET /mcp` returns **401** with:

```http
WWW-Authenticate: Bearer realm="edgars-knowledge", resource_metadata="https://HOST/.well-known/oauth-protected-resource/mcp", scope="openid profile email"
```

Protected resource JSON (shape):

```json
{
  "resource": "https://HOST",
  "authorization_servers": ["https://auth.edgars.tools"],
  "bearer_methods_supported": ["header"],
  "scopes_supported": ["openid", "profile", "email"]
}
```

Register ChatGPT’s OAuth redirect on `auth.edgars.tools` if not already present (see ChatGPT connector OAuth callback URL in the Apps UI).

## Tools ChatGPT will call

| Tool | Purpose |
|---|---|
| `search` | Company-knowledge / deep-research compatible search → `POST knowledge-api /search` |
| `fetch` | Fetch by id → expands via `/search` |
| `knowledge_search` | Same upstream search (richer MCP-shaped hits) |
| `knowledge_get` | Expand pointer/query |
| `knowledge_status` | Live upstream + backend probe |
| `knowledge_sources` | Semantic roles + runtime health |
| `knowledge_intake` | Optional bounded write via `/intake` |

For **company knowledge / deep research**, ChatGPT expects `search` + `fetch`. Both are aliases over the Knowledge API.

## Local run (canary)

```bash
cd /workspace/edgar-os/knowledge-mcp
export PUBLIC_BASE_URL=http://127.0.0.1:8787
export MCP_API_TOKEN=local-canary-token
python3 http_server.py
```

```bash
curl -sS http://127.0.0.1:8787/health
curl -sS http://127.0.0.1:8787/.well-known/oauth-protected-resource
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/mcp   # expect 401
curl -sS http://127.0.0.1:8787/mcp \
  -H "Authorization: Bearer local-canary-token" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## Env

| Env | Default | Meaning |
|---|---|---|
| `PUBLIC_BASE_URL` | `http://127.0.0.1:$PORT` | Canonical resource URL in OAuth metadata |
| `HOST` / `PORT` | `0.0.0.0` / `8787` | Bind address |
| `EDGARS_KNOWLEDGE_API` | `https://knowledge-api.edgars.tools` | Upstream |
| `EDGARS_AUTH_SERVER` | `https://auth.edgars.tools` | AS issuer in metadata |
| `MCP_API_TOKEN` | _(unset)_ | Local canary Bearer bypass |
| `MCP_TRUST_BEARER` | `1` | Accept any non-empty Bearer (ChatGPT OAuth) when not matching canary token |

## Health

`GET /health` → local ok + live `knowledge-api` `/health` body.
