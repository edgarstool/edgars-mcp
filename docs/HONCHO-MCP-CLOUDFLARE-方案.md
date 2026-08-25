# Honcho MCP × Cloudflare 整合方案

> 文件狀態（2026-08-17）：原有 Cloudflare MCP Portal 流程保留為 **legacy / 舊相容路徑**，供非 ChatGPT 的 agent、機器 client 與除錯用途；ChatGPT 將採用獨立的 `https://mcp.edgars.tools/chatgpt-honcho` gateway。下列為採用中的設計與驗收標準，**不代表 Cloudflare、ChatGPT OAuth 或部署已完成**。

## Legacy 結論：Portal 內建 Honcho 工具（非 ChatGPT）

採用 **edgars-mcp 內建 Honcho tools**。

不要再把 `honcho` 註冊成 Cloudflare AI Controls 的獨立 MCP server。`honcho` 之前卡在 bearer/header credential 與 Dashboard sync 狀態，且它是可重建控制面資源，繼續排查成本高於整合進已可用的 `edgars-mcp`。

既有／非 ChatGPT 流量：

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

## Legacy Cloudflare Portal 設定（非 ChatGPT）

這一節僅保留既有 Portal 的相容設定。`/chatgpt-honcho` 不加入 `edgars-entry` Portal，也不使用這條動態 `honcho__*` 工具面。

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

## Legacy repo 實作（非 ChatGPT）

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

## Legacy 驗收（非 ChatGPT）

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

## Legacy 回復方式（非 ChatGPT）

若 integrated Honcho tools 造成問題：

1. 先移除或暫時不設定 `HONCHO_API_KEY`，`tools/list` 會停止加入 `honcho__*`。
2. 若需要直連排查，可使用 `honcho-mcp.edgars.tools/mcp` fallback facade。
3. 不要優先重建 Cloudflare `honcho` server；那條路已標記為 deprecated。

## ChatGPT 專用 Honcho gateway（採用設計，待部署）

ChatGPT 不走上面的 Portal，也不能直接使用動態的 `honcho__*` 上游轉接。採用的正式 connector URL 是：

```text
https://mcp.edgars.tools/chatgpt-honcho
```

預期資料流：

```text
Desktop ChatGPT Web
→ Cloudflare Access Managed OAuth + DCR
→ mcp.edgars.tools/chatgpt-honcho
→ edgars-mcp 隔離 dispatcher
→ Honcho 官方 API（僅 server-side credential）
→ 固定 edgar-team / edgar 的表示與 conclusion
```

`DCR / Dynamic Client Registration / 動態用戶端註冊：讓 ChatGPT 在受控 OAuth 流程中註冊用戶端，不需要把長期 client secret 交給 ChatGPT。`

### Cloudflare 與身分邊界

`/chatgpt-honcho` 必須有**獨立、path-specific / 只匹配該 path**的 Cloudflare Access application，並採用：

- Managed OAuth 與 DCR；
- 僅必要的人類登入 Allow policy；
- 與既有 `/mcp` 分離的 Access audience。

它不得重用廣泛的 `edgars-mcp-direct` policy，也不得讓 ChatGPT 以 service token 登入。更重要的是，不要把此 route 加回 `edgars-entry` Portal；Portal 的 legacy 工具清單與 ChatGPT 工具面必須保持分離。

### 固定資料範圍與唯二工具

gateway 內部固定到：

```text
Honcho workspace = edgar-team
human peer = edgar
```

ChatGPT 不可傳入 workspace、peer、任意上游 URL、任意 HTTP method 或任意 Honcho tool 名稱。它也不得在正常工具呼叫中建立 peer、session 或呼叫 `get_peer_context`；任何既有 `chatgpt` peer 的清理／重建都必須是另一個明確、可審核的管理操作。

`tools/list` 必須只回傳：

| 工具 | 能力 | 強制限制 |
| --- | --- | --- |
| `recall_edgar_memory` | 唯讀回想 | 只讀固定 `edgar-team`／`edgar` 的相關記憶表示；沒有泛用 Honcho search、chat 或 raw API。 |
| `remember_edgar_memory` | append-only / 只追加結論寫入 | 只允許限定的非敏感 category，固定寫入 `edgar-team`／`edgar`，且每次都必須明確傳送 `confirm=true`。 |

不得暴露：

```text
honcho__*
generic upstream tools/call
任意 REST/API proxy
任意 workspace、peer 或 URL selector
peer/session 建立、更新或刪除操作
```

`remember_edgar_memory` 應受可逆 feature switch 控制；就算開啟也不是自動記憶、批次匯入、覆寫或刪除介面。

### 隱私與 runtime 設定

gateway 的 request、error 與審計 log 不得保存：

```text
recall query
remember content
Honcho representation
HONCHO_API_KEY、OAuth token 或 Access token
```

安全診斷可保留 route、工具名稱、結果狀態、category 與長度／筆數，但不應原樣記錄上游錯誤本文。

新的 route 由既有 runtime configuration source 注入；建議透過 Doppler 設定下列**名稱**，不得把值寫進 repo、聊天或 log：

```text
MCP_CLOUDFLARE_ACCESS_CHATGPT_HONCHO_AUD
HONCHO_CHATGPT_GATEWAY_ENABLED
HONCHO_CHATGPT_WRITE_ENABLED
```

- `MCP_CLOUDFLARE_ACCESS_CHATGPT_HONCHO_AUD` 僅供 `/chatgpt-honcho` 驗證新 Access application 的 audience。
- `HONCHO_CHATGPT_GATEWAY_ENABLED` 是整條 ChatGPT gateway 的啟用開關；關閉時此 route 直接不可用。
- `HONCHO_CHATGPT_WRITE_ENABLED` 只控制 `remember_edgar_memory`；回復時可先關閉它，保留 recall 的唯讀能力。

既有 `HONCHO_API_KEY` 仍只存在於 server-side runtime，不會傳給 ChatGPT、Cloudflare Portal 或外部 client。

### Desktop ChatGPT Web 驗收（尚待執行）

只有以下實證都成立時，才可宣稱 gateway 已完成：

1. Cloudflare 讀回證明專屬 app 精確匹配 `mcp.edgars.tools/chatgpt-honcho`，Managed OAuth、DCR、必要的人類 policy 與新 audience 都正確。
2. 外部未登入請求收到該 route 自己的 OAuth protected-resource metadata／挑戰；不能是 302、HTML login page 或既有 `/mcp` audience 的結果。
3. 在 **Desktop ChatGPT Web**（不是 iOS／Android ChatGPT）以 exact URL 新增 app、完成 OAuth，並成功 Scan tools／同步工具。
4. ChatGPT 實際顯示的清單恰為 `recall_edgar_memory` 與 `remember_edgar_memory`，沒有 `honcho__*` 或其他通用轉接工具。
5. 執行非敏感 recall；若驗證寫入，只能使用使用者同意、可長期保留的非敏感事實，並明確帶 `confirm=true`。不得為測試製造隨機或短期垃圾記憶。
6. 重新檢查結果與 log，確認沒有 query、content 或 representation 被寫入。
7. 新連線通過後，才在 ChatGPT app 清單移除**精確為** `https://api.honcho.dev/mcp` 的舊連線；不得影響任何其他 connector。

手機 Safari 畫面中看到已儲存 app，不構成 OAuth、工具掃描或實際工具呼叫驗收。

### ChatGPT gateway 回復方式

按影響最小的順序回復：

1. 將 `HONCHO_CHATGPT_WRITE_ENABLED` 關閉並重啟 runtime：保留 `recall_edgar_memory`、立即停用 append-only 寫入。
2. 若整條 route 有問題，只停用／收緊 `/chatgpt-honcho` 專屬 Access application，或回復支援該 route 的已驗證版本；不要改動 legacy Portal、既有 `/mcp` 流量或 `honcho__*` 相容用途。
3. 在 Desktop ChatGPT Web 移除新的 exact URL app，並以 UI 實際讀回確認連線已移除；只開 URL 或最小化視窗不是成功證據。
4. 若需要重新連線，重新建立專屬 Access/OAuth connector；不要把舊 `https://api.honcho.dev/mcp` 當作 ChatGPT gateway fallback。

回復不刪除 Honcho 正式記憶、既有 `edgar` peer、shared `HONCHO_API_KEY` 或 Portal 的其他 upstream；它們不屬於此可重建 connector 控制面。
