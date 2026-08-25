# Cloudflare Honcho MCP Dashboard Handoff

> 文件狀態（2026-08-17）：既有 Cloudflare MCP Portal 說明保留為 **legacy / 舊相容路徑**，可供非 ChatGPT 的機器 client 與除錯使用；ChatGPT 專用 gateway 的目標、驗收與回復規則見本文件新增章節。**這不是任何 Dashboard、OAuth 或部署已完成的宣告。**

## Legacy 決策：不要重建獨立 honcho MCP server

Honcho 走 `edgars-mcp` 內建工具：

```text
entry.edgars.tools/mcp
→ Cloudflare MCP Portal
→ edgars-mcp
→ honcho__* tools
→ mcp.honcho.dev
```

Cloudflare Portal 裡不需要獨立 `honcho` server。若 Dashboard 裡仍看得到舊的 `honcho` server，應視為 legacy / 舊設定；除非使用者明確要求保留 debug route，否則不要把它加回 `edgars-entry` portal。

## Legacy Portal 的瀏覽器確認（非 ChatGPT）

若需要操作 Cloudflare Dashboard，只做下列確認：

1. `edgars-entry` portal 包含 `edgars-mcp`。
2. `edgars-mcp` server 狀態是 Ready。
3. 不把獨立 `honcho` server 加入 `edgars-entry`。
4. 若需要看到 Honcho tools，請 sync `edgars-mcp` capabilities，而不是 sync `honcho`。

## Legacy 成功判準（非 ChatGPT）

```text
edgars-entry portal 可連線
edgars-mcp Ready
tools/list 透過 edgars-mcp 顯示 honcho__* tools
```

## Legacy Portal 不要再做

```text
建立 MCP server: honcho
把 https://honcho-mcp.edgars.tools/mcp 加入 Cloudflare Portal
把 HONCHO_FACADE_BEARER_VALUE 填進 Cloudflare AI Controls
要求外部 agent 直接持有 Honcho credential
```

這些是更早的獨立 server 方案，已被上方 legacy `edgars-mcp integrated Honcho tools` 相容路徑取代；該 legacy 路徑仍不等於 ChatGPT gateway。

## ChatGPT 專用 gateway：Dashboard／Web handoff（待執行）

ChatGPT 必須使用新的 exact URL，而不是本文件前半所述的 Portal：

```text
https://mcp.edgars.tools/chatgpt-honcho
```

兩條路徑的關係如下：

| 對象 | 入口 | Cloudflare 層 | 工具面 | 狀態／用途 |
| --- | --- | --- | --- | --- |
| 既有 agent、機器 client、除錯 | `entry.edgars.tools/mcp` → `edgars-entry` Portal | 既有 MCP Portal | `honcho__*` 動態轉接 | legacy 相容用途；不作 ChatGPT connector。 |
| Desktop ChatGPT Web | `mcp.edgars.tools/chatgpt-honcho` | 獨立 Cloudflare Access application | 兩個固定工具 | 已採用的目標設計；仍待部署與實機驗收。 |

不要把 `/chatgpt-honcho` 加回 `edgars-entry` Portal，也不要讓它暴露既有 `honcho__*`。此 gateway 的目的是縮小 ChatGPT 的認證與資料操作邊界，不是替換所有非 ChatGPT 的 Portal 用途。

### 必要的 Cloudflare Access 設定

建立或讀回一個**新的、path-specific / 只匹配此 path**的 Cloudflare Access application：

- destination 必須精確匹配 `mcp.edgars.tools/chatgpt-honcho`，不是整個 hostname，也不是既有 `/mcp`；
- 使用 Managed OAuth，並啟用 DCR；
- Allow policy 只保留必要的人類登入，不加 service token bypass；
- 不重用廣泛 `edgars-mcp-direct` 的混合 policy；
- 使用與既有 `/mcp` 不同的專屬 audience。

`DCR / Dynamic Client Registration / 動態用戶端註冊：讓 ChatGPT 在受控 OAuth 流程內註冊 client，而不必把長期 client secret 交給 ChatGPT。`

將新 audience 與受控寫入開關注入 runtime 時，只列下列 Doppler 設定**名稱**，不記錄值：

```text
MCP_CLOUDFLARE_ACCESS_CHATGPT_HONCHO_AUD
HONCHO_CHATGPT_GATEWAY_ENABLED
HONCHO_CHATGPT_WRITE_ENABLED
```

第一個名稱僅供新 route 驗證專屬 Access audience；第二個名稱是整條 gateway 的 feature switch / 功能開關；第三個名稱只控制 append-only 寫入。關閉寫入開關時仍保持唯讀，開啟也不會跳過每次寫入的 `confirm=true`。

### 固定資料邊界與工具清單

gateway 內部固定使用：

```text
Honcho workspace: edgar-team
Human memory peer: edgar
```

ChatGPT 不能指定 workspace、peer、上游 URL、HTTP method 或通用 Honcho tool。正常工具呼叫也不得建立 peer、session 或呼叫 `get_peer_context`。

Scan tools 成功時，工具清單只能有：

| 工具 | 類型 | 條件 |
| --- | --- | --- |
| `recall_edgar_memory` | 唯讀 | 固定讀取 `edgar-team`／`edgar` 的相關記憶表示。 |
| `remember_edgar_memory` | append-only / 只追加寫入 | 固定 `edgar-team`／`edgar`、只接受限定非敏感 category，且每次必須明確傳送 `confirm=true`。 |

下列內容不得被 ChatGPT 看見或呼叫：

```text
honcho__*
generic upstream tools/call
raw REST/API proxy
任意 workspace、peer 或 URL selector
peer/session 建立、更新或刪除操作
```

若既有 `chatgpt` Honcho peer 必須清理／重建，先精確列出、確認範圍與影響後，以獨立管理操作處理；gateway 的 recall／remember 不得偷偷產生這類副作用。

### 隱私與 log 規則

request、error 與審計 log 不得保存：

```text
recall query
remember content
Honcho representation
HONCHO_API_KEY、OAuth token 或 Access token
```

診斷只可保留 route、工具名、結果狀態、category 與非敏感長度／筆數；也不要原樣記錄上游錯誤本文。

### 執行與 Desktop ChatGPT Web 驗收（尚待執行）

1. 先確認新 path 沒有被既有 Access application、Portal 或 proxy 覆蓋；若歷史控制面混亂，優先建立新的專屬 application，不修改 legacy `/mcp`。
2. 建立／讀回新 application，確認 destination、Managed OAuth、DCR、唯一必要的人類 Allow policy 與專屬 audience 都精確命中。
3. 注入 runtime 設定並重啟 origin；未登入的外部請求應收到新 route 的 OAuth protected-resource metadata／挑戰，不能是 302、HTML login page 或既有 audience 的結果。
4. 在 **Desktop ChatGPT Web** 以 exact URL 新增 app、完成 OAuth、執行 Scan tools／同步工具。iOS／Android ChatGPT 只能觀察已儲存連線，不能取代驗收。
5. 確認清單剛好兩個工具；先以非敏感 recall 實測，再以使用者同意且可長期保留的非敏感事實測試 `remember_edgar_memory`，並帶 `confirm=true`。不得為測試寫入隨機或短期資料。
6. 重新讀取結果並抽樣檢查安全 log，確認沒有 raw query、content 或 representation。上述全數通過後，才可稱 ChatGPT gateway 已驗收。
7. 新連線驗收後，才從 ChatGPT app 清單移除**精確為** `https://api.honcho.dev/mcp` 的舊 app；不得碰其他 connector、Portal server 或 Cloudflare Access application。

### 回復與清理

1. 先關閉 `HONCHO_CHATGPT_WRITE_ENABLED` 並重啟 runtime：保留 `recall_edgar_memory`，停用 append-only 寫入。
2. 若整條 route 有問題，只停用／收緊 `/chatgpt-honcho` 專屬 Access application，或回復 origin 到已驗證版本；不要改動 legacy Portal、既有 `/mcp`、正式 Honcho memory 或其他 upstream。
3. 從 Desktop ChatGPT Web 移除新 app，並以 UI 實際讀回確認 OAuth 連線已移除；URL 開啟或視窗最小化不是成功證據。
4. 只有新 app 已驗收且進行清理時，才移除舊 `https://api.honcho.dev/mcp` app。此操作是可重建 connector 控制面變更，不是刪除 Honcho 資料。

本章不授權或聲稱實際變更 Dashboard、Doppler、ChatGPT app、peer 或部署；每項操作必須以當下控制面讀回與端到端實測為準。
