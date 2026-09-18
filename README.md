# mcp-handcraft

Edgar 的本地 MCP（Model Context Protocol）Server。

讓任何支援 MCP 的 AI（Claude、OpenClaw 等）能透過 HTTP 直接操作本機電腦，包含：檔案系統、Git、系統指令、瀏覽器、Obsidian Vault、Linear、Warp、Cursor、Factory.ai、AI 代理委派、免費圖片生成。

**目前內建工具數量：70 個**（另加 `wrap_catalog`；最後校對：2026-09-08）

> 啟動改走 **Windows native**：直接跑 `server_http.py`，**不依賴 Docker / 1Password Connect / op run**。
> 對外授權預設 **Descope JWT**（`MCP_DESCOPE_*` + `MCP_AUTH_SERVER`）；本機仍可用 `MCP_API_TOKEN` bearer。
> 搞不清 mcp / webhooks / hooks 哪個是哪個？請看 **[網域分工（新手版）](docs/網域分工-新手版.md)**。
> 想把 Honcho / 其他 MCP 統一放到 Cloudflare Portal？請看 **[Honcho MCP 上 Cloudflare 方案](docs/HONCHO-MCP-CLOUDFLARE-方案.md)**。
> 要交給瀏覽器代理修 Cloudflare Dashboard credential？請看 **[Honcho MCP Dashboard Handoff](docs/CLOUDFLARE-HONCHO-MCP-DASHBOARD-HANDOFF.md)**。

---

## 架構

```
mcp-handcraft/
├── server_http.py      ← 主 HTTP MCP Server（port 8765，所有工具都在這）
├── server.py           ← stdio 入口（供本地 stdio client 使用）
├── run.cmd             ← 啟動 stdio server
├── run_http.cmd        ← 啟動 HTTP server（native：User/Machine 環境變數 + Descope）
├── run_stdio.cmd       ← 啟動 stdio proxy（Cursor / Hermes → 本機 HTTP MCP）
├── cloudflare/
│   └── workers/        ← hooks/status Worker 的 source-of-truth
├── config/
│   ├── mcp.local.example.json
│   ├── mcp.remote.example.json
│   └── mcp.remote.stdio.example.json
├── docs/
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

> **⚠️ 啟動前必填:`MCP_API_TOKEN`（Machine 或 User 環境變數）**
>
> HTTP server 啟動時會讀 `MCP_API_TOKEN`，**沒設會直接中止**（fail-fast）。
> 登入自動啟動：工作排程 `edgars-mcp-http` → `scripts\Start_Handcraft_MCP_HTTP.vbs` → `scripts\start-handcraft-http-at-login.ps1`。
> 授權：對外走 Descope（`MCP_DESCOPE_ENABLED=true`）；本機仍可用 Bearer `MCP_API_TOKEN`。不要把 token 寫進命令列或 shell history。
>
> 最小啟動範例：
>
> ```powershell
> .\run_http.cmd
> # 或：powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1
> # 或：登入任務 / VBS 開啟（同上）
> # → 監聽 http://127.0.0.1:8765/mcp
> ```
>
> 缺 token 時 server 會印 `MCP_API_TOKEN is required and must be a non-empty string. Refusing to start.` 後以失敗狀態退出。


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

這會先確認 `http://127.0.0.1:8765/health`，必要時用 `start-mcp.ps1`（native）啟動 `server_http.py`；再確認 `cloudflared` 程序；最後檢查 `https://mcp.edgars.tools/mcp`。

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

這個腳本會確認本機 `:8765` 健康，必要時透過 Windows-native `start-mcp.ps1` / `run_http.cmd` 啟動 `server_http.py`。本機 MCP bearer 只從 User/Machine 環境讀取，不寫入 profile、launcher 或 shell history。

### 只啟動 HTTP server（native，不經 Docker / 1Password）

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

需要驗證帶 Bearer token 的 `/mcp` 路徑時，不要把 token 寫進命令列。讓 `MCP_API_TOKEN` 由 User/Machine 環境提供，再用 wrapper 送 header：

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
| Descope | public MCP OAuth / JWT resource-server authorization |
| Playwright | `powershell -File .\scripts\setup-playwright.ps1`（browser 工具需要；含 pip + Chromium） |
| Claude Code | `winget install Anthropic.ClaudeCode` + `claude auth login` |
| Ollama | 本地模型執行環境 |
| OpenAI tunnel-client | OpenAI Secure MCP Tunnel 用；本 repo snapshot 未附安裝腳本 |

---

## 認證

目前 canonical auth 分兩層：

1. **Public MCP** `https://mcp.edgars.tools/mcp`
   - 授權由 **Descope Agentic OAuth / JWT** 負責。
   - `server_http.py` 以 `descope_resource_server` 模式驗證外部 access token。
   - `MCP_AUTH_SERVER=https://auth.edgars.tools`；對外 discovery 以 Descope Agentic authorization server 為準。
   - Cloudflare Tunnel 只負責 hostname → origin transport，不是 MCP 的 OAuth issuer。

2. **Localhost / local tools**
   - `http://127.0.0.1:8765/mcp`
   - 可使用 `MCP_API_TOKEN` bearer。
   - token 只從 Process / User / Machine environment 讀取，不寫入 launcher、repo 或命令列。

### ChatGPT / remote MCP client

| 欄位 | 值 |
|------|----|
| 連接器名稱 | `edgars mcp` |
| MCP 伺服器 URL | `https://mcp.edgars.tools/mcp` |
| 驗證 | `OAuth` |
| OAuth provider | Descope |
| Transport | Streamable HTTP |

Public OAuth acceptance：

- `/.well-known/oauth-protected-resource` / `/mcp` discovery 指向 Descope authorization server。
- 未授權呼叫 `/mcp` 回 `401` 並帶正確 `WWW-Authenticate`。
- 完成 OAuth 後能 `initialize -> tools/list -> tools/call`。
- `/health` 顯示 `oauth_mode=descope_resource_server`、`descope_enabled=true`。

### Local agent / stdio

`stdio_proxy.py` 預設轉送 `http://127.0.0.1:8765/mcp`，使用本機 `MCP_API_TOKEN`。遠端 agent 若走公開 URL，應使用 Descope OAuth access token。

歷史 incident / migration 文件仍保留供追查，但不代表目前 production auth contract。

---

## 工具總覽（既有工具全部保留）

另加永遠可見的 `wrap_catalog`。Playwright / Windows-MCP / Desktop Commander / Descope / cloudflared / 1Password Connect / OpenMontage / Hermes / OpenClaw 的完整工具面**預設關閉**，不是刪掉。

開啟方式（可全開或單開）：

```powershell
$env:MCP_WRAP_ALL = "1"   # 或單開 MCP_WRAP_PLAYWRIGHT / MCP_WRAP_WINDOWS / MCP_WRAP_DESKTOP_COMMANDER / MCP_WRAP_DESCOPE / MCP_WRAP_CLOUDFLARED / MCP_WRAP_OP_CONNECT / MCP_WRAP_OPENMONTAGE / MCP_WRAP_HERMES / MCP_WRAP_OPENCLAW
$env:MCP_WRAP_ALLOW_REMOTE = "1"  # 預設本機才能呼叫桌面類工具；要給遠端就再開這個
```

啟用後會以前綴展開完整上游 `tools/list`，不裁切：`pw__*`、`win__*`、`dc__*`、`descope__*` / `descope_mgmt__*`、`om__*`，以及 `cloudflared_cli`、`op_connect_cli`、`hermes_cli`、`openclaw_cli` 全 CLI。

驗證：

```powershell
py -3 .\scripts\verify-wrapped-tools.py
```

### 🤖 AI 代理（10）

| 工具 | 說明 |
|------|------|
| `codex_agent` | 委派任務給 Codex AI（程式碼實作、檔案編輯） |
| `gemini_agent` | 委派任務給 Gemini CLI（快速通用任務） |
| `claude_code_agent` | 委派任務給 Claude Code（複雜重構、多檔操作） |
| `copilot_agent` | 委派任務給 GitHub Copilot CLI（本機改 code、跑指令） |
| `droid_agent` | 委派任務給 Factory Droid CLI（`droid exec`） |
| `ollama_agent` | 委派任務給本地 Ollama 模型（離線可用） |
| `smart_agent` | 智慧輪替：Gemini → Copilot → Droid → Codex → Claude Code |
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

需要環境變數：`WARP_API_KEY`（在 [oz.warp.dev/settings](https://oz.warp.dev/settings) 產生，前綴 `wk-`）。

---

### 🖱 Cursor Cloud Agents（4）

| 工具 | 說明 |
|------|------|
| `cursor_agents_list` | 列出 Cursor 雲端 agent |
| `cursor_agent_get` | 查單一 agent 詳情 |
| `cursor_agent_create` | 建立 agent 並送出第一個 prompt（可選 repo URL） |
| `cursor_agent_run_status` | 查 agent 某次 run 狀態 |

需要環境變數：`CURSOR_API_KEY`（Cursor Dashboard → API Keys）。

---

### 🏭 Factory.ai / Droid（4）

| 工具 | 說明 |
|------|------|
| `factory_sessions_list` | 列出 Droid sessions（部分 org 需開通） |
| `factory_session_get` | 查單一 session 詳情 |
| `factory_computers_list` | 列出 Droid Computers（持久開發環境） |
| `factory_readiness_reports` | 列出 repo agent readiness 報告 |

需要環境變數：`FACTORY_API_KEY`（[app.factory.ai/settings/api-keys](https://app.factory.ai/settings/api-keys)）。

---

### 🖼 圖片生成（1）

| 工具 | 說明 |
|------|------|
| `image_generate_free` | 免費圖片生成（Pollinations.AI，不需 API key），存為 PNG 到 `.screenshots/` |

> 模型選項：`flux`（預設，高品質）、`turbo`（快速）、`gptimage`

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
python -m unittest test_server_http.py -v
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-HandcraftSecureStartup.ps1
```

---

## 環境變數（Windows User / Machine scope）

| 變數 | 說明 |
|------|------|
| `MCP_API_TOKEN` | localhost / local tools / stdio proxy bearer；native startup 仍要求非空 |
| `MCP_DESCOPE_ENABLED` | public MCP 使用 Descope resource-server auth；目前預設 `true` |
| `MCP_DESCOPE_PROJECT_ID` | Descope project id |
| `MCP_DESCOPE_RESOURCE_SERVER_ID` | Descope Agentic resource server id |
| `MCP_DESCOPE_AUDIENCE` | 預設 `https://mcp.edgars.tools/mcp` |
| `MCP_AUTH_SERVER` | canonical auth vanity URL：`https://auth.edgars.tools` |
| `MCP_BASE_URL` | public base URL：`https://mcp.edgars.tools` |
| `MCP_BIND_HOST` | Windows origin bind host；目前 8765 由 cloudflared 轉發 |
| `PERPLEXITY_API_KEY` | web_search |
| `OPENAI_API_KEY` | OpenAI tools |
| `LINEAR_API_KEY` | Linear issue management |
| `TRACKTW_API_KEY` | TrackTW |
| `WARP_API_KEY` | Warp Oz |
| `CURSOR_API_KEY` | Cursor Cloud Agents |
| `FACTORY_API_KEY` | Factory.ai / Droid |
| `HONCHO_API_KEY` | Honcho |
| `EDGARS_HONCHO_MCP_FACADE_TOKEN` | Honcho MCP facade |
| `MCP_AGENT_TIMEOUT_SECONDS` | Agent timeout |
| `MCP_PORT` | local HTTP port；預設 8765 |
| `MCP_WRAP_ALL` | wrapper 總開關 |
| `MCP_WRAP_PLAYWRIGHT` / `MCP_WRAP_WINDOWS` / `MCP_WRAP_DESKTOP_COMMANDER` / `MCP_WRAP_DESCOPE` / `MCP_WRAP_CLOUDFLARED` / `MCP_WRAP_OPENMONTAGE` / `MCP_WRAP_HERMES` / `MCP_WRAP_OPENCLAW` | Windows-native wrapper switches |
| `MCP_WRAP_OP_CONNECT` | legacy 1Password Connect wrapper；canonical startup 固定為 `0` |
| `MCP_WRAP_ALLOW_REMOTE` | 是否允許遠端 client 呼叫桌面類 wrapper |

啟動路徑不使用 Docker、1Password Connect、`op run` 或 Doppler。Secrets 不寫入 launcher；由 Windows Process/User/Machine environment 繼承。

---

## 公開端點

```
https://mcp.edgars.tools/mcp
```

透過 Cloudflare Tunnel 對外；**Tunnel 只做 transport，MCP authorization 由 Descope 負責**。

Acceptance：

- public `/health` 與本機 origin 必須一致，並顯示 `oauth_mode=descope_resource_server`、`descope_enabled=true`。
- `/.well-known/oauth-protected-resource` 必須指向 Descope authorization server。
- 未授權 `/mcp` 應回 `401`；完成 Descope OAuth 後必須可 `initialize -> tools/list -> tools/call`。

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

本 repo 內未保留 `gateway.cmd`；目前 HTTP 啟動路徑是 `edgars-mcp-http` → `Start_Handcraft_MCP_HTTP.vbs` → `start-handcraft-http-at-login.ps1`，或 `run_http.cmd` / `scripts\Start-HandcraftStack.ps1`。全部走 Windows native，不經 Docker、1Password、`op run` 或 Doppler。手動探測 `/mcp` 時請使用 `scripts\Invoke-HandcraftMcp.ps1`，避免 bearer 出現在 shell history 或程序命令列。

---

## 相關連結

- Linear Project：WHO 系列 issues
- Agent-KB：`G:\Agent-KB`
- Vault：`G:\Obsidian\Edgar'sObsidianVault`
- Screenshots：`V:\projects\edgars-mcp\.screenshots\`
