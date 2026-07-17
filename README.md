# mcp-handcraft

Edgar 的本地 MCP（Model Context Protocol）Server。

讓任何支援 MCP 的 AI（Claude、OpenClaw 等）能透過 HTTP 直接操作本機電腦，包含：檔案系統、Git、系統指令、瀏覽器、Obsidian Vault、Linear、Notion、Warp、Cursor、Factory.ai、AI 代理委派、免費圖片生成。

**目前工具數量：70 個**（最後校對：2026-07-15）

> 不懂 Doppler 要填什麼？請看 **[Doppler 設定指南（新手版）](docs/DOPPLER-設定指南-新手版.md)**。  
> 搞不清 mcp / webhooks / hooks 哪個是哪個？請看 **[網域分工（新手版）](docs/網域分工-新手版.md)**。

---

## 架構

```
mcp-handcraft/
├── server_http.py      ← 主 HTTP MCP Server（port 8765，所有工具都在這）
├── server.py           ← stdio 入口（供本地 stdio client 使用）
├── archive/
│   └── minimax/       ← 已封存的 MiniMax handlers（不再接進主 server）
├── run.cmd             ← 啟動 stdio server
├── run_http.cmd        ← 啟動 HTTP server（透過 Doppler 注入 secrets）
├── run_stdio.cmd       ← 啟動 stdio proxy（Cursor / Hermes → 本機 HTTP MCP）
├── cloudflare/
│   └── workers/        ← hooks/status Worker 的 source-of-truth
├── config/
│   ├── mcp.local.example.json
│   ├── mcp.remote.example.json
│   └── mcp.remote.stdio.example.json
├── docs/
│   ├── DOPPLER-設定指南-新手版.md
│   └── MCP-CLIENT-AUTH-最小正式方案.md
├── scripts/
│   ├── start-mcp.ps1 ← 開啟：背景啟動 HTTP + 可選 cloudflared（寫 PID）
│   ├── check-mcp.ps1 ← 檢驗：本機 / 外網 / MCP handshake
│   ├── maintain-mcp.ps1 ← 維護：日誌輪替、健康修復、可選 smoke test
│   ├── stop-mcp.ps1 ← 停止 HTTP（可選 cloudflared）
│   ├── Start-HandcraftStack.ps1 ← 舊版一鍵啟動（仍可用）
│   └── Test-HandcraftHealth.ps1 ← 輕量健康檢查（check-mcp 會涵蓋更多）
└── test_server_http.py ← smoke test
```

---

## 啟動方式

> **⚠️ 啟動前必填:`MCP_API_TOKEN`**
>
> HTTP server 啟動時會讀 `MCP_API_TOKEN`,**沒設會直接中止**(fail-fast,不做 fallback)。
> Token 由 Doppler 集中管理,啟動腳本自動注入,不要寫進命令列或 shell history。
>
> 最小啟動範例(`run_http.cmd` 自動走這條):
>
> ```powershell
> # 1. 拿 token (需要先 doppler setup --project handcraft-mcp --config prd)
> $env:MCP_API_TOKEN = doppler secrets get MCP_API_TOKEN --plain
> # 2. 啟動 server
> python .\server_http.py
> # → 監聽 http://127.0.0.1:8765/mcp,POST 要求 Authorization: Bearer <token>
> ```
>
> 缺 token 時 server 會印 `MCP_API_TOKEN is required` 後 exit。


### Ops 腳本 trio（建議）

```powershell
cd V:\projects\edgars-mcp

# 開啟（背景執行，寫 PID 至 G:\AI_WORK_512\run\mcp-handcraft\）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1

# 檢驗（本機 health + MCP handshake + 外網 /mcp）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp.ps1

# 維護（日誌輪替；不健康時自動重啟）
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\maintain-mcp.ps1 -RestartIfUnhealthy

# 停止
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-mcp.ps1
```

### 一鍵恢復本機 + tunnel + public MCP（舊腳本）

```powershell
cd V:\projects\edgars-mcp
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-HandcraftStack.ps1
```

這會先確認 `http://127.0.0.1:8765/health`，必要時用 Doppler 啟動 `server_http.py`；再確認 `cloudflared` 程序；最後檢查 `https://mcp.edgars.tools/mcp` 是否回 200。

### 啟動 OpenAI Secure MCP Tunnel（私有 MCP，不開公開入口）

> 注意：本 repo 目前**沒有**保留 `Start-OpenAISecureMcpTunnel.ps1` / `Install-OpenAITunnelClient.ps1`。  
> 若之後要恢復這條路徑，請先把對應腳本重新納入 repo，再更新本段操作說明。

OpenAI Secure MCP Tunnel 會讓本機 `tunnel-client` 對 OpenAI 建立 outbound HTTPS 連線，再把 OpenAI 端的 MCP JSON-RPC 請求轉發到本機 `http://127.0.0.1:8765/mcp`。這條路徑不需要把本機 MCP server 暴露到 public internet。

先在 OpenAI Platform tunnel settings 建立 / 選取 tunnel，取得 `tunnel_id`，並準備一把具備 Tunnels Read + Use 權限的 runtime API key。不要把 key 寫進 repo 或命令列歷史。

```powershell
# 目前僅保留概念說明；腳本檔未納入此 repo snapshot
```

只跑診斷、不啟動長跑 tunnel：

```powershell
# 目前僅保留概念說明；腳本檔未納入此 repo snapshot
```

這個腳本會確認本機 `:8765` 健康，必要時透過 Doppler 啟動 `server_http.py`，再用 `sample_mcp_remote_no_auth` profile 執行 `tunnel-client init`、`doctor` 和 `run`。本機 MCP bearer 會透過 `Authorization: env:MCP_API_TOKEN` 這類 env reference 傳給 `tunnel-client`，不寫入 profile。保持該 process 運作時，ChatGPT / Codex / API 端才可透過 tunnel 呼叫本機 MCP。

### 只啟動 HTTP server（透過 Doppler 注入 secrets）

```powershell
cd V:\projects\edgars-mcp
.\run_http.cmd
```

### 確認運作中

```powershell
netstat -ano | Select-String ':8765'
Invoke-RestMethod http://127.0.0.1:8765/health
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-HandcraftHealth.ps1
```

需要驗證帶 Bearer token 的 `/mcp` 路徑時，不要把 token 寫進命令列。先讓 `MCP_API_TOKEN` 由 Doppler 或目前 shell 的環境變數提供，再用 wrapper 送 header：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Invoke-HandcraftMcp.ps1
```

### 停止

```powershell
netstat -ano | Select-String ':8765'
Stop-Process -Id <OwningProcessId> -Force
```

---

## 環境需求

| 項目 | 說明 |
|------|------|
| Python | 3.11+ |
| Doppler | secrets 管理，project `handcraft-mcp`，config `prd` |
| Playwright | `powershell -File .\scripts\setup-playwright.ps1`（browser 工具需要；含 pip + Chromium） |
| Claude Code | `winget install Anthropic.ClaudeCode` + `claude auth login` |
| Ollama | 本地模型執行環境 |
| OpenAI tunnel-client | OpenAI Secure MCP Tunnel 用；本 repo snapshot 未附安裝腳本 |

---

## 認證

目前建議把認證分成兩層看：

1. **外網公開入口** `https://mcp.edgars.tools/mcp`
   - 建議交給 **Cloudflare Access + Managed OAuth**
   - 外部 MCP client 應走 Cloudflare Access 的 discovery / authorize / token 流程
   - `server_http.py` 只把 Cloudflare Access 視為上游身分來源，不再以 repo 內建 OAuth 當外網主流程

2. **本機 / localhost**
   - `http://127.0.0.1:8765/mcp`
   - 仍可使用 `MCP_API_TOKEN`
   - 供 `stdio_proxy.py`、維運腳本、smoke test、migration 使用

### 外網 `/mcp`

若已啟用 Cloudflare Access，外網 `POST /mcp` 會由 Access 先做登入與 OAuth，origin 端再驗證 `Cf-Access-Jwt-Assertion`。

外網 client 需要：

```
Authorization: Bearer <access_token>
```

### ChatGPT 自訂連接器填寫

| 欄位 | 值 |
|------|----|
| 連接器名稱 | `edgars mcp` |
| MCP 伺服器 URL | `https://mcp.edgars.tools/mcp` |
| 驗證 | `OAuth` |
| OAuth 提供者 | Cloudflare Access Managed OAuth |
| Client ID / Secret | 以 Cloudflare Access application 或 portal 顯示值為準 |
| 傳輸 | 可串流 HTTP |

Cloudflare Access 啟用後，OAuth discovery / redirect / token 以 Cloudflare Access 為準。  
repo 內建這組端點：

```text
https://mcp.edgars.tools/.well-known/oauth-authorization-server
https://mcp.edgars.tools/.well-known/oauth-protected-resource
```

只有在 **localhost / migration 模式** 下才建議直接用。當 `MCP_CLOUDFLARE_ACCESS_ENABLED=true` 且 public hostname 走 Access 時，repo 內建 `/authorize`、`/token`、`/register` 不再是外網主流程。

### Codex / Claude / Hermes 的最小正式 auth 方案

建議直接分三條路：

1. **Edgar 本機**
   - `stdio_proxy.py` -> `http://127.0.0.1:8765/mcp`
   - 用 `MCP_API_TOKEN`
2. **遠端 / 雲端 agent**
   - `stdio_proxy.py` -> `https://mcp.edgars.tools/mcp`
   - 用 Cloudflare Access service token
   - headers:
     - `CF-Access-Client-Id`
     - `CF-Access-Client-Secret`
3. **人類互動式 public client**
   - 走 Cloudflare Access Managed OAuth

詳細版請看：

- [docs/MCP-CLIENT-AUTH-最小正式方案.md](docs/MCP-CLIENT-AUTH-最小正式方案.md)
- [docs/CHATGPT-OAUTH-INCIDENT-2026-07-06.md](docs/CHATGPT-OAUTH-INCIDENT-2026-07-06.md)
- [config/mcp.local.example.json](config/mcp.local.example.json)
- [config/mcp.remote.stdio.example.json](config/mcp.remote.stdio.example.json)

---

## 工具總覽（78 個）

### 🤖 AI 代理（10）

| 工具 | 說明 |
|------|------|
| `codex_agent` | 委派任務給 Codex AI（程式碼實作、檔案編輯） |
| `kilo_agent` | 委派任務給 Kilo CLI（快速通用任務） |
| `claude_code_agent` | 委派任務給 Claude Code（複雜重構、多檔操作） |
| `copilot_agent` | 委派任務給 GitHub Copilot CLI（本機改 code、跑指令） |
| `droid_agent` | 委派任務給 Factory Droid CLI（`droid exec`） |
| `ollama_agent` | 委派任務給本地 Ollama 模型（離線可用） |
| `smart_agent` | 智慧輪替：Kilo → Copilot → Droid → Codex → Claude Code |
| `agent_job_status` | 查詢背景 agent job 進度 |
| `agent_job_list` | 列出所有背景 jobs |
| `agent_job_cleanup` | 清除已完成的舊 jobs |

> 長任務建議加 `"async": true`，先拿 `job_id`，再用 `agent_job_status` 輪詢。

---

### 📁 檔案系統（7）

| 工具 | 說明 |
|------|------|
| `fs_list` | 列出資料夾內容 |
| `fs_read` | 讀取檔案內容 |
| `fs_write` | 寫入或覆蓋檔案 |
| `fs_move` | 移動或重命名檔案/資料夾 |
| `fs_delete` | 刪除檔案（不可逆，謹慎使用） |
| `fs_search` | 全文搜尋檔案內容 |
| `fs_disk_info` | 查看磁碟使用量 |

---

### ⚙️ 系統（3）

| 工具 | 說明 |
|------|------|
| `sys_run` | 執行 PowerShell 指令（危險指令會被攔截） |
| `sys_info` | 查看 CPU、記憶體、系統資訊 |
| `sys_processes` | 列出執行中的程序 |

> `sys_run` 內建黑名單，會阻擋 `format`、`diskpart`、`del /f /s /q c:\` 等破壞性指令。

---

### 🔧 Git（4）

| 工具 | 說明 |
|------|------|
| `git_status` | 查看 repo 狀態（modified/untracked/staged） |
| `git_log` | 查看 commit 歷史 |
| `git_diff` | 查看變更內容 |
| `git_commit` | 建立 commit |

---

### 🌐 瀏覽器（9）

| 工具 | 說明 |
|------|------|
| `browser_screenshot` | 對網頁截圖，存到 `.screenshots/`（headless） |
| `browser_get_text` | 擷取網頁純文字內容（headless） |
| `browser_run_script` | 在網頁上執行 JavaScript（headless） |
| `browser_visible_open` | 跳出可見 Chrome 視窗並開啟 URL（本機信任客戶端） |
| `browser_visible_navigate` | 在可見 session 內換網址 |
| `browser_visible_click` | 在可見 session 內點擊元素 |
| `browser_visible_type` | 在可見 session 內輸入文字 |
| `browser_visible_screenshot` | 對目前可見 session 截圖 |
| `browser_visible_close` | 關閉可見瀏覽器 |

> headless 工具需要 Playwright + Chromium：`playwright install chromium`  
> 可見瀏覽器預設用本機已安裝的 Chrome（`BROWSER_VISIBLE_CHANNEL=chrome`）。  
> 遠端 OAuth 客戶端（例如 ChatGPT）無法叫出桌面瀏覽器；Cursor / Hermes stdio 可以。

---

### 🔍 網路搜尋（1）

| 工具 | 說明 |
|------|------|
| `web_search` | 用 Perplexity AI 搜尋，回傳含引用來源的結果 |

---

### 📦 TrackTW 物流（2）

> 預設停用：`tracktw_carriers`、`tracktw_package_status` 不會出現在 `tools/list`；若要重新啟用，請在伺服器設定 `MCP_ENABLED_TOOLS=tracktw_carriers,tracktw_package_status` 後重啟。

| 工具 | 說明 |
|------|------|
| `tracktw_carriers` | 列出或搜尋 TrackTW 支援的物流商 / 店家關鍵字 |
| `tracktw_package_status` | 用物流商 / 店家 + 單號查貨態，回傳目前階段、`from_status -> to_status` 時間軸、`current_event_time`、到貨推估，可匯出 CSV / Excel |

範例：

```json
{
  "carrier_name": "黑貓",
  "tracking_number": "1234567890",
  "export_report": true,
  "report_format": "xlsx"
}
```

報告預設輸出到：

```text
V:\projects\edgars-mcp\reports
```

---

### 📋 Linear（3）

| 工具 | 說明 |
|------|------|
| `linear_issues` | 列出 issues（可篩選狀態/優先級） |
| `linear_create_issue` | 建立新 issue，並重新查詢確認 issue 已建立 |
| `linear_update_issue` | 更新 issue 狀態或新增留言，並重新查詢確認狀態/留言已落地 |

---

### ⚡ Warp Oz Cloud Agents（3）

| 工具 | 說明 |
|------|------|
| `warp_agent_runs_list` | 列出 Warp 雲端 agent 執行紀錄 |
| `warp_agent_run_status` | 查單一 run 狀態（JSON 詳情） |
| `warp_agent_run_create` | 用 prompt + `environment_id` 啟動新 run |

需要 Doppler：`WARP_API_KEY`（在 [oz.warp.dev/settings](https://oz.warp.dev/settings) 產生，前綴 `wk-`）。

---

### 🖱 Cursor Cloud Agents（4）

| 工具 | 說明 |
|------|------|
| `cursor_agents_list` | 列出 Cursor 雲端 agent |
| `cursor_agent_get` | 查單一 agent 詳情 |
| `cursor_agent_create` | 建立 agent 並送出第一個 prompt（可選 repo URL） |
| `cursor_agent_run_status` | 查 agent 某次 run 狀態 |

需要 Doppler：`CURSOR_API_KEY`（Cursor Dashboard → API Keys）。

---

### 🏭 Factory.ai / Droid（4）

| 工具 | 說明 |
|------|------|
| `factory_sessions_list` | 列出 Droid sessions（部分 org 需開通） |
| `factory_session_get` | 查單一 session 詳情 |
| `factory_computers_list` | 列出 Droid Computers（持久開發環境） |
| `factory_readiness_reports` | 列出 repo agent readiness 報告 |

需要 Doppler：`FACTORY_API_KEY`（[app.factory.ai/settings/api-keys](https://app.factory.ai/settings/api-keys)）。

---

### 📝 Notion（2）

| 工具 | 說明 |
|------|------|
| `notion_get_page` | 讀取 Notion 頁面內容 |
| `notion_search` | 搜尋 Notion workspace |

---

### 🖼 圖片生成（1）

| 工具 | 說明 |
|------|------|
| `image_generate_free` | 免費圖片生成（Pollinations.AI，不需 API key），存為 PNG 到 `.screenshots/` |

> 模型選項：`flux`（預設，高品質）、`turbo`（快速）、`gptimage`

---

### 🔌 Repo-local Browser MCP Plugins（4）

這 4 個整合已改成 repo-local plugin / repo 內插件註冊，不再塞進 `server_http.py` 主工具清單。用途是讓 `edgars-mcp` 可以順手提供常用瀏覽器 / web automation 的 MCP 入口模板。

| Plugin | 用途 | 主要需求 |
|--------|------|----------|
| `chrome-devtools` | 直接接 Chrome DevTools 做除錯 / 自動化 | Chrome + Node.js |
| `comet` | 讓 AI 透過 Perplexity Comet 做研究 / 瀏覽 | Comet Browser + Node.js |
| `kapture` | 用 Chrome extension 做多 client 瀏覽器控制 | Kapture extension + Node.js |
| `playwright` | 通用瀏覽器自動化 / 測試 | Node.js |

插件入口在 `plugins/`，marketplace 註冊在 `.agents/plugins/marketplace.json`。

---

### 📓 Obsidian Vault（13）

Vault 路徑：`G:\Obsidian\Edgar'sObsidianVault`（備援：`G:\AgentKB\Obsidian\Edgar'sObsidianVault`）

| 工具 | 說明 |
|------|------|
| `vault_read` | 讀取筆記內容 |
| `vault_write` | 建立或覆蓋筆記，寫入後讀回確認內容 |
| `vault_append` | 在筆記末尾附加內容，附加後讀回確認內容 |
| `vault_list` | 列出資料夾內容 |
| `vault_search` | 全文搜尋所有筆記 |
| `vault_delete` | 刪除筆記（移到 .trash，可復原） |
| `vault_move` | 移動或重命名筆記 |
| `vault_daily_note` | 取得或建立今日日記 |
| `vault_recent` | 列出最近修改的筆記 |
| `vault_tasks` | 列出所有未完成任務（- [ ]） |
| `vault_tags` | 列出所有 tags 及使用次數 |
| `vault_create_from_template` | 用模板建立新筆記 |
| `vault_sort_inbox` | **自動整理 Inbox**：掃描散落筆記，依內容分類搬到正確 PARA 資料夾 |

#### Vault 結構（PARA 方法）

```
00 Inbox/          ← 先丟這裡，之後用 vault_sort_inbox 整理
01 Projects/       ← 正在進行的專案
02 Areas/          ← 持續維護的領域（AI環境、架構、工具）
03 Resources/      ← 參考資料、指令、指南
04 Archive/        ← 封存的舊內容
Templates/         ← 筆記模板
```

#### 可用模板

| 模板名稱 | 用途 |
|---------|------|
| `Daily Notes` | 每日日記 |
| `AI 任務卡` | 多代理 AI 任務追蹤（對應 Agent-KB 格式） |
| `Agent 交接備忘` | Agent 間任務移交紀錄 |
| `每日 Agent 彙整` | 每日 Agent 使用總結 |
| `工具研究筆記` | 新工具評估記錄 |
| `Meeting Notes` | 會議記錄 |
| `Weekly Review` | 每週回顧 |
| `Decision Record` | 架構決策記錄（ADR 格式） |
| `Project` | 專案追蹤 |
| `Learning Project` | 學習專案 |
| `Research Clipping` | 網路資料剪輯 |
| `Resource` | 工具/文件資源 |

---

## Smoke Test

```powershell
cd V:\projects\edgars-mcp
doppler run -- python -m unittest test_server_http.py -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-HandcraftSecureStartup.ps1
```

---

## 環境變數（由 Doppler 管理）

| 變數 | 說明 |
|------|------|
| `MCP_API_TOKEN` | localhost / smoke test / stdio proxy 的 bearer token |
| `MCP_CLOUDFLARE_ACCESS_ENABLED` | `true` 時 public `/mcp` 走 Cloudflare Access JWT 驗證 |
| `MCP_CLOUDFLARE_ACCESS_TEAM_DOMAIN` | 例如 `team-name.cloudflareaccess.com` |
| `MCP_CLOUDFLARE_ACCESS_AUD` | Cloudflare Access application 的 AUD |
| `MCP_CLOUDFLARE_ACCESS_JWKS_URL` | 可選；預設 `https://<team-domain>/cdn-cgi/access/certs` |
| `MCP_CLOUDFLARE_ACCESS_DISABLE_BUILTIN_OAUTH` | 預設 `true`；public hostname 停用 repo 內建 OAuth 端點 |
| `MCP_CLOUDFLARE_ACCESS_ALLOW_PUBLIC_TOKEN_FALLBACK` | 過渡期才用；允許 public `/mcp` 回退到舊 bearer 模式 |
| `MCP_OAUTH_CLIENT_ID` | repo 內建 OAuth 的 localhost / migration client id（預設 `handcraft-mcp`） |
| `MCP_OAUTH_CLIENT_SECRET` | repo 內建 OAuth 的 localhost / migration client secret |
| `MCP_OAUTH_AUTH_CODE_TTL_SECONDS` | repo 內建 OAuth 授權碼有效秒數（預設 600） |
| `MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS` | repo 內建 OAuth access token 有效秒數（預設 7776000） |
| `PERPLEXITY_API_KEY` | web_search 用 |
| `OPENAI_API_KEY` | 備用 |
| `LINEAR_API_KEY` | Linear issue 管理 |
| `NOTION_API_KEY` | Notion 讀取 |
| `TRACKTW_API_KEY` | TrackTW 物流查詢 |
| `WARP_API_KEY` | Warp Oz 雲端 agent API |
| `CURSOR_API_KEY` | Cursor Cloud Agents API |
| `FACTORY_API_KEY` | Factory.ai / Droid API |
| `MCP_AGENT_TIMEOUT_SECONDS` | Agent 等待上限（預設 300 秒） |
| `MCP_BASE_URL` | 公開 URL（預設 https://mcp.edgars.tools） |
| `MCP_WEBHOOK_BASE_URL` | webhook 對外 URL；若要分流到 `hooks.*`，在這裡設定 |
| `MCP_PACKAGE_WEBHOOK_TOKEN` | package webhook 共用 secret（可用 `Authorization: Bearer` 或 `X-Handcraft-Webhook-Token`） |
| `MCP_LINEAR_WEBHOOK_TOKEN` | Linear webhook 共用 secret |
| `MCP_DISCORD_WEBHOOK_TOKEN` | Discord webhook 共用 secret |
| `MCP_PORT` | 本機 HTTP port（預設 8765；測試可覆蓋） |

---

## 公開端點

```
https://mcp.edgars.tools/mcp
```

透過 Cloudflare Tunnel 對外。建議搭配 **Cloudflare Access Managed OAuth**，不要再把 repo 內建 OAuth 當外網主流程。

注意：

- public `/mcp` 在 Access 開啟後，探測可能會看到 **401 / 302 / Cloudflare Access login**，這代表 edge 可達，但**不等於 ChatGPT OAuth 已可用**。
- 若目標是 ChatGPT Connector / OAuth 全綠，還必須另外確認 `/.well-known/oauth-protected-resource` 可匿名讀取並回 `200`。
- 若要強制保護 direct URL，請直接在 `mcp.edgars.tools` 掛 Access，不要只靠 portal 隱藏。

OpenAI Secure MCP Tunnel 是另一條私有路徑：`tunnel-client` 從本機 outbound 連到 OpenAI，OpenAI 產品透過 OpenAI-hosted tunnel endpoint 呼叫本機 MCP。它不需要 `mcp.edgars.tools`，也不需要開 inbound firewall port。

### Hermes stdio proxy

Hermes 這類只會啟動 stdio MCP server 的 client，可改啟動：

```powershell
python .\stdio_proxy.py
```

預設會轉送到 `http://127.0.0.1:8765/mcp`。如果 HTTP endpoint 不在本機預設位置，可設定 `MCP_URL`。

### Package webhook

給 TrackTW / 包裹通知使用的 webhook URL。  
若 `MCP_WEBHOOK_BASE_URL` 已設成獨立 hostname（例如 `https://hooks.mcp.edgars.tools`），請用那個值：

```text
https://mcp.edgars.tools/webhook/package
```

本機對應 endpoint 是：

```text
http://127.0.0.1:8765/webhook/package
```

這條不是 MCP endpoint。對方要「接 MCP」時給 `/mcp`；對方要「包裹 webhook」時給 `/webhook/package`。

### Linear webhook

給 Linear webhook 使用的 URL。  
若 `MCP_WEBHOOK_BASE_URL` 已設成獨立 hostname，請用那個值：

```text
https://mcp.edgars.tools/webhook/linear
```

這條不是 MCP endpoint。對方要「接 Linear webhook」時給 `/webhook/linear`（或 `/webhooks/linear`）。

**Hermes Agent × Linear OAuth**（授權機器人帳號，與上面的個人 API Key 不同）：

```text
https://mcp.edgars.tools/linear/oauth/authorize   ← 開始授權
https://mcp.edgars.tools/linear/oauth/callback  ← Linear 跳回
https://mcp.edgars.tools/linear/oauth/status    ← 檢查是否已授權
```

設定步驟見 `docs/Linear-OAuth設定-新手版.md`；manifest 在 `config/linear-oauth-manifest.json`。

webhook 不會走 Cloudflare Access 的瀏覽器登入流程。若要保留公開直打，至少配置：

- `MCP_PACKAGE_WEBHOOK_TOKEN`
- `MCP_LINEAR_WEBHOOK_TOKEN`
- `MCP_DISCORD_WEBHOOK_TOKEN`

並讓呼叫方用 `Authorization: Bearer <secret>` 或 `X-Handcraft-Webhook-Token` 送進來。本檔不保存 token，也不要把 runtime log、`.screenshots/`、`__pycache__/` 或圖片檔 commit 進 repo。

本 repo 內未保留 `gateway.cmd`；目前 HTTP / gateway 相關啟動路徑是 `run_http.cmd` 與 `scripts\Start-HandcraftStack.ps1`，兩者都走 Doppler/env 注入，不需要把 token 當參數傳入。手動探測 `/mcp` 時請使用 `scripts\Invoke-HandcraftMcp.ps1`，避免 `Authorization: Bearer ...` 出現在 shell history 或程序命令列。

---

## 相關連結

- Linear Project：WHO 系列 issues
- Agent-KB：`G:\Agent-KB`
- Vault：`G:\Obsidian\Edgar'sObsidianVault`
- Screenshots：`V:\projects\edgars-mcp\.screenshots\`
