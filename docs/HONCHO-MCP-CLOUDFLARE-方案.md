# Honcho MCP 上 Cloudflare 方案

> 目標：把 Honcho MCP 與其他常用 MCP 統一放進 Cloudflare AI Controls / MCP Portals，讓 agent 走單一入口取得工具，同時避免 Cloudflare Access、OAuth、Bearer token 多層互相攔截。

## 結論

推薦採用 **Cloudflare MCP Portal 聚合模式 + edgars-mcp 本機 facade**，不要一開始就重寫 Honcho MCP。

```text
Agent / bot
→ Cloudflare MCP Portal（entry.edgars.tools/mcp）
→ upstream MCP servers
   ├─ edgars-mcp（https://mcp.edgars.tools/mcp，Bearer）
   ├─ honcho（https://honcho-mcp.edgars.tools/mcp，Bearer facade）
   ├─ linear / notion / github / cloudflare docs ...
   └─ future MCP servers
```

原因：

1. Honcho 官方已提供 remote MCP server：`https://mcp.honcho.dev`。
2. Cloudflare MCP Portal 本來就是「多 MCP server 單一入口」。
3. Cloudflare 2026-06-26 起支援 MCP Portal service token，適合 autonomous agents / bots，不必每個 agent 走瀏覽器 OAuth。
4. 這條路重建成本低，符合 Agent-KB 的「可重建設定優先重建」規則。

目前已驗證的正式接線：

```text
Cloudflare MCP Portal / AI Controls
→ https://honcho-mcp.edgars.tools/mcp
→ Cloudflare Tunnel remote ingress
→ localhost:8765
→ server_http.py Honcho facade
→ https://mcp.honcho.dev
```

`server_http.py` 會在 `Host: honcho-mcp.edgars.tools` 且 path 為 `/mcp` 時，把請求轉給 Honcho 官方 MCP，並注入 Honcho 必要 headers。這保留標準 MCP path，避免 Cloudflare AI Controls 對非 `/mcp` path 的相容性問題。

## 不推薦的第一版

暫時不要一開始就做：

```text
把 Honcho MCP server 本體重寫成 Cloudflare Worker
```

這不是不能做，而是第一版成本較高：

1. 要完整複製 Honcho MCP 的 tools schema 與行為。
2. 要維護 Honcho API adapter。
3. 要處理 streaming / Streamable HTTP / session state。
4. 會多一層自維護 surface，日後 Honcho 官方 MCP 更新時容易 drift。

除非需要自訂工具、快取、審計或把多個 Honcho workspace 包成固定工具組，否則先用官方 remote MCP 比較乾淨。

## 官方依據

- Honcho 官方 MCP 文件：`https://honcho.dev/docs/v3/guides/integrations/mcp`
- Honcho MCP server URL：`https://mcp.honcho.dev`
- Cloudflare remote MCP server 文件：`https://developers.cloudflare.com/agents/model-context-protocol/guides/remote-mcp-server/`
- Cloudflare MCP Portal 文件：`https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/`
- Cloudflare MCP Portal service token changelog：`https://developers.cloudflare.com/changelog/post/2026-06-26-mcp-portal-service-tokens/`

## Honcho MCP 需要的 headers

Honcho 官方 remote MCP 需要：

```text
Authorization: Bearer <HONCHO_API_KEY>
X-Honcho-User-Name: <user-name>
```

可選：

```text
X-Honcho-Assistant-Name: <assistant-name>
X-Honcho-Workspace-ID: <workspace-id>
```

建議 Edgar 環境固定：

```text
X-Honcho-User-Name: Edgar
X-Honcho-Workspace-ID: edgar-team
```

不同 agent 可用不同 assistant name：

```text
codex
claude
hermes
openclaw
cursor
```

## Doppler secrets 建議

放在 `handcraft-mcp / prd`，不要放 repo。

```text
HONCHO_API_KEY
HONCHO_USER_NAME
HONCHO_WORKSPACE_ID
HONCHO_ASSISTANT_NAME_CODEX
HONCHO_ASSISTANT_NAME_CLAUDE
HONCHO_ASSISTANT_NAME_HERMES
```

若使用 Cloudflare Worker facade fallback，再放 Cloudflare Worker secrets：

```text
HONCHO_API_KEY
HONCHO_USER_NAME
HONCHO_WORKSPACE_ID
```

## Cloudflare AI Controls 設定

### 1. MCP Server: honcho

在 Cloudflare Zero Trust：

```text
Access controls
→ AI controls
→ MCP servers
→ Add an MCP server
```

建議設定：

```text
Name: honcho
Server ID: honcho
HTTP URL: https://honcho-mcp.edgars.tools/mcp
Authentication: bearer / header-based
```

Header：

```text
Authorization: Bearer <EDGARS_HONCHO_MCP_FACADE_TOKEN>
```

注意：Honcho 官方 MCP 需要多個 upstream headers，因此不要把 `https://mcp.honcho.dev` 直接放進 Cloudflare AI Controls，除非 Cloudflare UI/API 明確支援多 header credential。曾觀察到直接設定會出現 `Invalid header name.`。

目前 API 重建觀察：

```text
curl 直打 https://honcho-mcp.edgars.tools/mcp + facade token = 200 tools/list
Cloudflare AI Controls unauthenticated probe = 會打到 origin，origin 回 401
Cloudflare AI Controls bearer probe = sync 顯示 unable to connect to server，origin log 未看到請求
Cloudflare AI Controls `PUT /servers/honcho` 覆寫同 URL + auth_credentials 後 = PUT success，但 sync_success=false，仍未 Ready
```

這代表 origin / tunnel / DNS / facade 都是通的，剩餘卡點是 Cloudflare AI Controls 控制面對新 bearer server 的 credential 寫入或同步狀態。若 API 建立或 PUT 後仍不打 origin，優先用 Dashboard 重新設定該 server 的 header-based auth，而不是繼續追 origin。

### 2. MCP Portal: edgars-entry

Portal 放所有 MCP：

```text
Portal name: edgars-entry
Portal URL: https://entry.edgars.tools/mcp
Servers:
  - edgars-mcp
  - honcho
  - linear
  - cloudflare docs
  - github / notion / obsidian / future servers
```

對 bots / agents：

1. Portal Access application 加 Service Auth policy。
2. 每個 linked MCP server 的 Access application 也加同一個 Service Auth policy。
3. 對不需要 per-user OAuth 的 server 關閉 `Require user auth` / `on_behalf=false`。

## edgars-mcp facade 模式

當 Cloudflare MCP server UI 不能設定多個 upstream headers，或想把多個 agent 固定成不同 assistant name，可先用本 repo 的 `server_http.py` 當 facade：

```text
Cloudflare MCP Portal / AI Controls
→ https://honcho-mcp.edgars.tools/mcp
→ Cloudflare Tunnel
→ server_http.py facade
→ https://mcp.honcho.dev
```

facade 負責：

1. 驗證 incoming `Authorization: Bearer <EDGARS_HONCHO_MCP_FACADE_TOKEN>`。
2. 對 upstream Honcho 加：
   - `Authorization: Bearer <HONCHO_API_KEY>`
   - `X-Honcho-User-Name`
   - `X-Honcho-Workspace-ID`
   - `X-Honcho-Assistant-Name`
3. 原樣 proxy MCP Streamable HTTP request / response。

這不是完整 MCP server 實作，只是 HTTP proxy / header injector。好處是重建快、風險低。

環境變數：

```text
EDGARS_HONCHO_MCP_FACADE_TOKEN
HONCHO_API_KEY
HONCHO_USER_NAME=Edgar
HONCHO_WORKSPACE_ID=edgar-team
HONCHO_ASSISTANT_NAME=codex
HONCHO_MCP_HOSTNAME=honcho-mcp.edgars.tools
```

Cloudflare Tunnel remote ingress：

```text
honcho-mcp.edgars.tools -> http://localhost:8765
```

驗收：

```powershell
$token = doppler secrets get EDGARS_HONCHO_MCP_FACADE_TOKEN --project handcraft-mcp --config prd --plain
$body = '{ "jsonrpc":"2.0", "id":1, "method":"tools/list", "params":{} }'

curl.exe -i https://honcho-mcp.edgars.tools/mcp `
  -H "Authorization: Bearer $token" `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  --data $body
```

## Worker facade fallback

Worker 版本已保留在 repo，適合未來要把 Honcho facade 從本機服務移到 Cloudflare edge 時使用：

```text
cloudflare/workers/honcho-mcp-facade/
├─ index.mjs
├─ wrangler.jsonc
└─ README.md
```

Wrangler secrets：

```text
HONCHO_API_KEY
EDGARS_HONCHO_MCP_FACADE_TOKEN
HONCHO_USER_NAME
HONCHO_WORKSPACE_ID
HONCHO_ASSISTANT_NAME
```

Worker 路由：

```text
https://honcho.edgars.tools/mcp
```

已知限制：Worker facade 直打 `https://honcho.edgars.tools/mcp` 可回 Honcho tools/list，但 Cloudflare AI Controls sync 測試沒有打到 Worker origin，仍回 `unable to connect to server`。因此目前正式 portal 路徑先使用 `honcho-mcp.edgars.tools/mcp`。

驗收：

```powershell
# 無 token 應 401
curl.exe -i https://honcho.edgars.tools/mcp

# 有 token 應進入 Honcho MCP flow
curl.exe -i https://honcho.edgars.tools/mcp `
  -H "Authorization: Bearer <EDGARS_HONCHO_MCP_FACADE_TOKEN>"
```

## 所有 MCP 上架原則

每個 MCP server 要先分類，不要全部套同一種 auth。

| 類型 | 例子 | Cloudflare 放法 |
|---|---|---|
| 已有 hosted remote MCP | Honcho, Cloudflare MCP | 直接加進 MCP servers |
| 本機工具 MCP | edgars-mcp | Tunnel 或 Worker facade，origin 用 Bearer |
| 需要多 header 的 MCP | Honcho, private upstream | edgars-mcp facade、Worker facade 或 Cloudflare Agents `addMcpServer` |
| 需要人類 OAuth 的 MCP | GitHub, Google | Portal + per-user OAuth |
| agent/bot 專用 MCP | edgars-mcp, honcho memory | Portal service token + `on_behalf=false` |

## 驗收清單

1. `edgars-mcp` 在 Cloudflare AI Controls 顯示 Ready。
2. `honcho` 在 Cloudflare AI Controls 顯示 Ready。
3. `entry.edgars.tools/mcp` 可以列出 edgars-mcp 與 honcho 工具。
4. service token client 可以連 portal，不需要瀏覽器 OAuth。
5. Honcho tools 至少能回：
   - `inspect_workspace`
   - `list_peers`
   - `get_peer_card`
6. 無認證直打 upstream 不應暴露 secrets。
7. Cloudflare Access / old app / old policy 不再攔截 machine route。

## Rollback

如果 honcho server 加進 Cloudflare 後造成 portal 異常：

1. 從 MCP Portal 先移除 `honcho`。
2. 若仍異常，刪除 Cloudflare AI Controls 裡的 `honcho` MCP server。
3. 若使用 Worker facade，停用 route `honcho.edgars.tools` 或 rollback Worker deploy。
4. 若使用 tunnel facade，從 Cloudflare Tunnel remote ingress 移除 `honcho-mcp.edgars.tools`，或刪除該 DNS CNAME。
5. 保留 Honcho 官方直連方式：

```text
https://mcp.honcho.dev
Authorization: Bearer <HONCHO_API_KEY>
X-Honcho-User-Name: Edgar
```

## 下一步

推薦順序：

1. 在 Cloudflare Dashboard 編輯或重建 `honcho` server，使用 `https://honcho-mcp.edgars.tools/mcp` 與 `Authorization: Bearer <EDGARS_HONCHO_MCP_FACADE_TOKEN>`。
2. 同步 `honcho`，確認狀態 Ready 且 tools 至少包含 `inspect_workspace`。
3. 把 `honcho` 加回 `edgars-entry` portal。
4. 再把其他 MCP servers 逐一整理進 `config/mcp.cloudflare.catalog.example.json`。
5. 最後用 Cloudflare API 或 Terraform 管理 portal / servers，避免 UI drift。
