# Honcho MCP 入口網站整合方案

> 目標：讓外部 agent 只連 `https://entry.edgars.tools/mcp`，由 Cloudflare MCP Portal 進入 `edgars-mcp`，再由 `edgars-mcp` 代理 Honcho 官方 MCP tools。

## 結論

採用 **edgars-mcp 內建 Honcho tools**。

不要再把 `honcho` 註冊成 Cloudflare AI Controls 的獨立 MCP server。`honcho` 之前卡在 bearer/header credential 與 Dashboard sync 狀態，且它是可重建控制面資源，繼續排查成本高於整合進已可用的 `edgars-mcp`。

正式流量：

```text
external agents
→ https://entry.edgars.tools/mcp
→ Cloudflare MCP Portal
→ edgars-mcp
→ tools/list 顯示 honcho__* tools
→ tools/call honcho__<tool>
→ https://mcp.honcho.dev
```

`origin / 來源服務：真正處理請求的後端服務。`

`upstream / 上游服務：目前服務再往後呼叫的目標服務。`

`facade / 外觀代理：對外看起來像一個簡單服務，內部替你處理複雜 headers 或轉接。`

## Cloudflare 設定

Portal 只需要保留：

```text
edgars-entry
├─ edgars-mcp
└─ linear（若仍需要互動 OAuth）
```

不要加入：

```text
honcho
```

原因：Honcho 官方 MCP 需要 `Authorization`、`X-Honcho-User-Name`、`X-Honcho-Workspace-ID`、`X-Honcho-Assistant-Name` 等 upstream headers。這些應由 `edgars-mcp` server-side 注入，不該讓 Cloudflare Portal 或外部 agent 直接持有。

## Repo 實作

`server_http.py` 會：

- 在 `tools/list` 時呼叫 Honcho 官方 MCP `tools/list`。
- 將每個 Honcho tool 改名成 `honcho__<upstream_tool_name>`。
- 在 `tools/call` 收到 `honcho__*` 時，移除 prefix 後呼叫 Honcho 官方 MCP `tools/call`。
- 使用 `HONCHO_API_KEY`、`HONCHO_USER_NAME`、`HONCHO_WORKSPACE_ID`、`HONCHO_ASSISTANT_NAME` 注入上游 headers。
- 快取 Honcho tools list，預設 TTL 為 `HONCHO_TOOLS_CACHE_TTL_SECONDS=60`。
- Honcho 不可用時不讓整個 `edgars-mcp tools/list` 失敗；最多回傳沒有 Honcho tools 或使用上一份 cache。

保留的 debug / fallback：

```text
https://honcho-mcp.edgars.tools/mcp
```

這條仍可由 `server_http.py` host-based facade 轉到 Honcho 官方 MCP，但它不是 Portal 的正式 upstream。

## Secrets 邊界

外部 agent 不直接拿：

```text
HONCHO_API_KEY
EDGARS_HONCHO_MCP_FACADE_TOKEN
HONCHO_FACADE_BEARER_VALUE
```

外部 agent 只連：

```text
https://entry.edgars.tools/mcp
```

本機 origin 可以從 Doppler、Windows env、1Password 或其他 secret manager 注入：

```text
HONCHO_API_KEY
HONCHO_USER_NAME=Edgar
HONCHO_WORKSPACE_ID=edgar-team
HONCHO_ASSISTANT_NAME=codex
```

Doppler 是 runtime secret source 之一，不是外部 agent 的連線目標。

## 驗收

本機測試：

```powershell
python -m py_compile server_http.py test_server_http.py
python -m unittest test_server_http.HonchoMcpFacadeTests
```

預期：

```text
tools/list 包含 honcho__inspect_workspace 或其他 honcho__* tools
tools/call honcho__inspect_workspace 會轉成 upstream tools/call name=inspect_workspace
Cloudflare Portal 不需要獨立 honcho server
```

Cloudflare 驗收：

1. 確認 `edgars-mcp` server 狀態 Ready。
2. 確認 `edgars-entry` portal 只有必要 upstream，例如 `edgars-mcp`、`linear`。
3. Sync `edgars-mcp` capabilities。
4. 從真實 MCP client 連 `https://entry.edgars.tools/mcp`，確認工具清單出現 `honcho__*`。

## 回復方式

若 integrated Honcho tools 造成問題：

1. 先移除或暫時不設定 `HONCHO_API_KEY`，`tools/list` 會停止加入 `honcho__*`。
2. 若需要直連排查，可使用 `honcho-mcp.edgars.tools/mcp` fallback facade。
3. 不要優先重建 Cloudflare `honcho` server；那條路已標記為 deprecated。
