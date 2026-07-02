# MCP OAuth（mcp.edgars.tools）

本文件說明 `server_http.py` 內建 OAuth 授權伺服器如何讓雲端 MCP client（ChatGPT、Cursor、自架 agent）連線。

## 為什麼不再硬編 client_id

舊做法在程式碼裡維護 `ALLOWED_CLIENT_IDS` / ChatGPT URL 白名單，每次新 client 都要改 code、重 deploy。這不符合 [MCP 2025-11-25 Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) 與 OAuth Client ID Metadata Documents（CIMD）。

現在支援三種 **標準** client 註冊方式（依 MCP 建議優先順序）：

| 方式 | 適用對象 | client_id 從哪來 |
|------|----------|------------------|
| **CIMD**（首選） | ChatGPT、OpenAI Chat、任何能自架 metadata JSON 的 client | HTTPS URL，例如 `https://chatgpt.com` |
| **DCR**（動態註冊） | 需要 server 發配 client_id 的 agent | `POST /register` 回傳 |
| **Pre-registered**（bootstrap） | 本機 / migration 用 | 環境變數 `MCP_OAUTH_CLIENT_ID`（預設 `handcraft-mcp`） |

## Discovery 端點

| 端點 | 用途 |
|------|------|
| `/.well-known/oauth-protected-resource` | RFC 9728 Protected Resource Metadata（`resource` = `/mcp` canonical URI） |
| `/.well-known/oauth-protected-resource/mcp` | 同上（path suffix alias，ChatGPT / RFC 9728 建議） |
| `/.well-known/oauth-authorization-server` | OAuth AS metadata（含 DCR、CIMD、PKCE） |
| `/.well-known/openid-configuration` | OIDC discovery（issuer、authorize、token、scopes） |
| `/authorize` | Authorization Code + PKCE |
| `/token` | Token exchange |
| `/register` | Dynamic Client Registration (RFC 7591) |

## 方式一：CIMD（ChatGPT / 雲端 agent 推薦）

Client 用 **HTTPS URL** 當 `client_id`。Authorization Server 會：

1. GET 該 URL 取得 JSON metadata
2. 驗證 `client_id` 欄位與 URL **完全一致**
3. 驗證 `redirect_uri` 必須出現在 metadata 的 `redirect_uris` 陣列（精確比對）
4. 依 HTTP `Cache-Control` 快取（最長 24 小時）

Metadata 最少需要：

```json
{
  "client_id": "https://chatgpt.com",
  "client_name": "ChatGPT",
  "redirect_uris": [
    "https://chatgpt.com/connector/oauth/callback"
  ],
  "token_endpoint_auth_method": "none"
}
```

Public client 必須走 **PKCE S256**，token 交換時**不需要** `client_secret`。

## 方式二：DCR（Dynamic Client Registration）

```http
POST /register
Content-Type: application/json

{
  "client_name": "My Agent",
  "redirect_uris": ["https://agent.example/oauth/callback"],
  "token_endpoint_auth_method": "none"
}
```

- `token_endpoint_auth_method: "none"` → public client，不回傳 `client_secret`，授權時強制 PKCE
- 省略或使用 `client_secret_post` → confidential client，會回傳 `client_secret`

## 方式三：Pre-registered bootstrap（handcraft-mcp）

本機 smoke test、stdio proxy、migration 可用環境變數：

| 變數 | 預設 |
|------|------|
| `MCP_OAUTH_CLIENT_ID` | `handcraft-mcp` |
| `MCP_OAUTH_CLIENT_SECRET` | `handcraft-mcp-client-secret` |

此 client 允許動態 `redirect_uri`（僅建議 localhost / 開發用），仍支援 PKCE 免 secret 換 token。

## PKCE 與 Public Client

- 所有 public client（CIMD、`token_endpoint_auth_method: none`、無 secret 的 DCR）在 `/authorize` **必須**帶 `code_challenge` + `code_challenge_method=S256`
- `/token` 用 `code_verifier` 驗證，可不送 `client_secret`

## Cloudflare Access 與內建 OAuth

若 `MCP_CLOUDFLARE_ACCESS_ENABLED=true` 且 `MCP_CLOUDFLARE_ACCESS_DISABLE_BUILTIN_OAUTH=true`（預設），對外 hostname `mcp.edgars.tools` 的 discovery / authorize / token / register 會回 404，改由 **Cloudflare Access Managed OAuth** 處理。

本機 `127.0.0.1:8765` 或關閉上述開關時，仍可使用 repo 內建 OAuth 流程。

## 環境變數

| 變數 | 說明 |
|------|------|
| `MCP_OAUTH_CLIENT_ID` | Bootstrap pre-registered client id |
| `MCP_OAUTH_CLIENT_SECRET` | Bootstrap client secret |
| `MCP_OAUTH_AUTH_CODE_TTL_SECONDS` | 授權碼 TTL（預設 600） |
| `MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS` | Access token TTL（預設 7776000） |
| `MCP_OAUTH_CIMD_CACHE_TTL_SECONDS` | CIMD 快取上限（預設 86400） |
| `MCP_OAUTH_CIMD_FETCH_TIMEOUT_SECONDS` | 拉 metadata 逾時（預設 10） |

## 驗證

```powershell
cd V:\projects\mcp-handcraft
python -m unittest test_server_http.OAuthFlowTests -v
```
