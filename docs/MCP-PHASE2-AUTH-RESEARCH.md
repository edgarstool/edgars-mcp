# MCP Phase 2 研究結論（授權為主、工具為輔）

日期：2026-09-05  
對齊文件：`docs/MCP-01-C.md`、`docs/MCP-01-P.md`、官方 FastMCP / MCP spec / OpenAI Apps auth  
狀態：研究與判斷，不是整包重寫

## 一句話

手刻主體（78+ tools、webhook、業務邏輯）留下。FastAPI 只當 HTTP 外殼。FastMCP 只接手「OAuth discovery + 401 挑戰 + 多種 token 驗證」。不要把 tools 搬進 FastMCP，也不要自己再寫一層 JSON-RPC。

## 你真正卡住的不是功能不夠，是授權層分裂

現況 handcraft 同時扛了太多角色：

1. MCP resource server（驗證 token）
2. 有時當 authorization server（內建 `/authorize` `/token` `/register`）
3. 有時把這層讓給 Cloudflare Access Managed OAuth（會**取代**你的 401）
4. 有時再疊 Descope JWT
5. 本機還要靜態 Bearer `MCP_API_TOKEN`

不同 client 要的東西不一樣：

| Client | 要什麼 | 不能怎樣 |
|---|---|---|
| ChatGPT connector | PRM + AS metadata + CIMD/DCR + PKCE + `resource` | 不能帶 CF service token header |
| Cursor / Claude Desktop `type: http` | 通常不會帶自訂 header，也不會完整 OAuth | 不能直接打 CF Access 保護的入口 |
| Hermes / stdio proxy | 可帶 Bearer 或 CF Access header | 本機要 fail-fast |
| 本機 smoke | 靜態 token | 不要逼它走瀏覽器登入 |

這就是「每換一個授權就碰壁」的根因：client 種類 × 三層 auth × Cloudflare 改寫 401。不是 tools 不夠。

## 官方怎麼切層（這次上網對過）

### MCP 規格（resource server ≠ authorization server）

MCP HTTP server **MUST** 當 OAuth 2.1 resource server，實作 RFC 9728 PRM。Client 用 PRM 去找 authorization server。401 要帶：

```http
WWW-Authenticate: Bearer resource_metadata="https://mcp.edgars.tools/.well-known/oauth-protected-resource"
```

來源：https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization

ChatGPT 官方也寫死：它會 query 你的 MCP server 拿 protected resource metadata；還要 echo `resource`、CIMD/DCR/預定義 client、PKCE S256。  
來源：https://developers.openai.com/apps-sdk/build/auth

### FastMCP 官方：授權只有三條路，對應「哪種授權都要快解」

來源：https://gofastmcp.com/servers/auth/authentication  
來源：https://gofastmcp.com/servers/auth/remote-oauth  
來源：https://gofastmcp.com/servers/auth/oauth-proxy  
來源：https://gofastmcp.com/integrations/descope

| 情況 | FastMCP 該用誰 | 白話 |
|---|---|---|
| IdP **有 DCR**（Descope、WorkOS AuthKit） | `RemoteAuthProvider` / `DescopeProvider` | MCP 只驗 JWT；登入交給 Descope |
| IdP **沒 DCR**（GitHub、Google、Azure 傳統 app） | `OAuthProxy` | FastMCP 對外假裝支援 DCR，對內用你預先註冊的 client |
| 本機 / 機器 token / 第二條 JWT | `MultiAuth` + extra `JWTVerifier` / static token | ChatGPT 走 OAuth，stdio 走 Bearer，同一入口 |
| 自己當完整 AS | `OAuthProvider` | **官方勸你不要**，除非隔離網。這正是 handcraft 現在最累的那塊 |

Descope 官方整合頁直接說：開 Descope MCP Server、開 DCR，然後：

```python
from fastmcp.server.auth.providers.descope import DescopeProvider
auth = DescopeProvider(config_url=..., base_url=...)
mcp = FastMCP(name="...", auth=auth)
```

來源：https://gofastmcp.com/integrations/descope

### FastAPI 官方接法（上一輪實作做錯的地方）

來源：https://gofastmcp.com/integrations/fastapi

正確：

```python
mcp_app = mcp.http_app(path="/")
app = FastAPI(lifespan=mcp_app.lifespan)  # 必傳 lifespan
app.mount("/mcp", mcp_app)
```

錯誤（上一輪踩到 307 / session manager 沒初始化）：

- 自己手寫 `/mcp` JSON-RPC 再 `await mcp.list_tools()`
- `app.mount` 卻不傳 `lifespan`
- 用 `FastMCP.from_fastapi()` 把 REST 轉成 tools（官方自己說 LLM 表現會明顯變差，只適合原型）

手刻 tools 應繼續當 **內層 handler**，不是改寫成一堆 `@mcp.tool()`。

## 對齊 MCP-01-C 的原判決（沒過期）

MCP-01-C 第 9 節已經寫過正確節奏：

1. **現在**：手刻補齊 discovery（PRM / AS metadata / issuer / 401 / Cloudflare 原樣轉發）
2. **中期**：FastAPI 當 HTTP 外層；PRM/WWW-Authenticate **局部**交給 FastMCP `RemoteAuthProvider`
3. **不要**：整包換成 FastMCP、不要把 tools 交給框架、不要在官方 SDK v2 未穩時押身家

這次上網只多證實兩件事：

- FastMCP 現在有現成 `DescopeProvider` + `MultiAuth`，比 2026-07-05 報告時更適合你「哪種授權都要解」
- FastMCP PyPI 主線已到 **4.0.3（2026-09-04）**。Phase 2 brief 鎖的是 `fastmcp==3.4.2`。升 4 是另一個決策，不要默默升

## 建議的目標架構（授權開關，不是功能重寫）

```
Client (ChatGPT / Cursor / Hermes / stdio)
        │
        ▼
FastAPI 外層
  CORS / 原樣 well-known / 不改路徑
  webhook / health / linear oauth 仍走手刻
        │
        ├─ GET  /.well-known/oauth-protected-resource[/mcp]
        │     FastMCP RemoteAuth / DescopeProvider 產生
        ├─ 401 WWW-Authenticate  resource_metadata=...
        │     FastMCP 產生
        └─ POST /mcp
              FastMCP http_app（lifespan 掛上）
                    │
                    ▼  token 驗證（MultiAuth）
              1. Descope JWT
              2. 內建 Bearer MCP_API_TOKEN
              3. （可選）OAuthProxy 給沒 DCR 的 IdP
                    │
                    ▼
              手刻 DISPATCH / server_http handlers
              （78+ tools 原封不動）
```

Cloudflare 只當 tunnel / TLS。**不要**再開 Access Managed OAuth 蓋掉 401。CF 官方自己寫：Managed OAuth replaces the 401 response behavior。這條在 MCP-01-C F13，現在仍然有效。

## 「哪種授權都拿得到」的決策表（之後照表接，不要再現場發明）

遇到新 client，只問三個問題：

1. 它會不會自己做 OAuth discovery？（ChatGPT 會；多數 Desktop `type: http` 不會）
2. 它的 IdP 有沒有 DCR？（Descope 有；GitHub/Google 沒有）
3. 它能不能帶靜態 header？（Hermes/stdio 能；ChatGPT 不能）

然後：

- 會 OAuth + 有 DCR → `DescopeProvider`
- 會 OAuth + 沒 DCR → `OAuthProxy`
- 不會 OAuth、能帶 header → `MCP_API_TOKEN` 或 CF service token 走 stdio/`mcp-remote`
- 兩個都要 → `MultiAuth`

不要再為第四種 client 新寫一套 AS。

## 功能面：你已經有的，不要再堆同質工具

handcraft 已經有：檔案、終端、瀏覽器、Obsidian、Linear、Notion、多代理委派、媒體生成、Honcho。再加「另一個操作網頁 / 另一個跑指令」沒有槓桿。

值得加的是**協議能力**，不是第 79 個 tool：

| 能力 | 為什麼跟授權/體驗有關 | 規格 |
|---|---|---|
| `server/discover` | 2026-07-28 現代 client 探測入口；舊 client 仍走 initialize | MCP 2026-07-28 changelog |
| 雙世代並存 | 舊 client 2025-11-25，新 client 2026-07-28 | 你 V2 清單已做一部分 |
| 未帶 token → 401 + PRM | ChatGPT 判定「有沒有實作 OAuth」 | MCP + OpenAI auth |
| 工具級 `_meta["mcp/www_authenticate"]` | ChatGPT 新要求：HTTP 401 不夠，tool 錯也要挑戰 | OpenAI Apps auth |
| ChatGPT `search` / `fetch` | 跟 OAuth 無關，但缺了會讓人以為 connector 壞了 | OpenAI MCP docs |
| Elicitation / 2026 MRTR `input_required` | 危險操作（刪檔、commit、發 webhook）改成 client 內確認，不必另做 UI | 2025-11-25 elicitation；2026-07-28 SEP-2322 |
| Tasks 擴充 | 長任務（video/agent job）改官方 polling，你已有自製 `agent_job_*` | 2026 把 tasks 移出核心變 extension |
| ChatGPT Apps UI | 把 kanban / 物流 / 記憶查詢做成可點的卡片，不是新後端 | OpenAI Apps SDK |

2026-07-28 大改（stateless、拿掉 initialize、拿掉 session id）**不能**現在整包跟。正確是：外層能講 2026-07-28（`server/discover`），內層繼續服務 2025-11-25。這跟 MCP-01-P、V2 清單一致。

## 明確不要做的

1. 不要把 78 個 tool 改寫成 `@mcp.tool()`
2. 不要 `FastMCP.from_fastapi()` 把 REST 反射成 MCP
3. 不要自己再實作一套 Streamable HTTP
4. 不要默默升 FastMCP 4.x（brief 鎖 3.4.2；4.0.3 另案）
5. 不要用 Cloudflare Access Managed OAuth 當 ChatGPT 的 IdP
6. 不要為了「更好玩」先加新工具；授權沒穩，新工具只會多一條 401 迷宮

## 建議的下一刀（仍屬 Phase 2.0/2.1，不動 master）

1. 外網 curl 五條 well-known + 無 token POST `/mcp`（MCP-01-C M1–M5），把 U2 從 Unknown 變事實
2. FastAPI 只做：CORS、lifespan mount、webhook 路由原樣
3. FastMCP 只接：`DescopeProvider` 或 `RemoteAuthProvider` + 內建 Bearer 的 `MultiAuth`
4. `/mcp` 業務仍 dispatch 到手刻 handlers
5. ChatGPT 路徑關掉 CF Managed OAuth，PRM 的 `resource` 必須是 `https://mcp.edgars.tools/mcp`（FastMCP #1348 舊坑）

## Sources

1. https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization
2. https://modelcontextprotocol.io/specification/2026-07-28/changelog
3. https://gofastmcp.com/servers/auth/authentication
4. https://gofastmcp.com/servers/auth/remote-oauth
5. https://gofastmcp.com/servers/auth/oauth-proxy
6. https://gofastmcp.com/integrations/fastapi
7. https://gofastmcp.com/integrations/descope
8. https://developers.openai.com/apps-sdk/build/auth
9. `docs/MCP-01-C.md`
10. `docs/MCP-01-P.md`
11. `docs/MCP-OAuth.md`
