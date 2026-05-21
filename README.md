# mcp-handcraft

Edgar 的本地 MCP（Model Context Protocol）Server。

讓任何支援 MCP 的 AI（Claude、OpenClaw 等）能透過 HTTP 直接操作本機電腦，包含：檔案系統、Git、系統指令、瀏覽器、Obsidian Vault、Linear、Notion、AI 代理委派、免費圖片生成。

**目前工具數量：56 個**

---

## 架構

```
mcp-handcraft/
├── server_http.py      ← 主 HTTP MCP Server（port 8765，所有工具都在這）
├── server.py           ← stdio 入口（供本地 stdio client 使用）
├── mmx_handlers.py     ← MiniMax 媒體生成 handlers
├── run.cmd             ← 啟動 stdio server
├── run_http.cmd        ← 啟動 HTTP server（透過 Doppler 注入 secrets）
├── scripts/
│   ├── Start-HandcraftStack.ps1 ← 啟動/驗證 :8765 + cloudflared + public /mcp
│   └── Test-HandcraftHealth.ps1 ← 明確健康檢查
└── test_server_http.py ← smoke test
```

---

## 啟動方式

### 一鍵恢復本機 + tunnel + public MCP

```powershell
cd C:\Users\EdgarsTool\Projects\mcp-handcraft
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-HandcraftStack.ps1
```

這會先確認 `http://127.0.0.1:8765/health`，必要時用 Doppler 啟動 `server_http.py`；再確認 `cloudflared` 程序；最後檢查 `https://mcp.whoasked.vip/mcp` 是否回 200。

### 只啟動 HTTP server（透過 Doppler 注入 secrets）

```powershell
cd C:\Users\EdgarsTool\Projects\mcp-handcraft
.\run_http.cmd
```

### 確認運作中

```powershell
netstat -ano | Select-String ':8765'
Invoke-RestMethod http://127.0.0.1:8765/health
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\Test-HandcraftHealth.ps1
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
| Playwright | `playwright install chromium`（browser 工具需要） |
| Claude Code | `winget install Anthropic.ClaudeCode` + `claude auth login` |
| Ollama | 本地模型執行環境 |
| mmx CLI | MiniMax 媒體生成 |

---

## 認證

HTTP MCP endpoint 支援兩種 bearer token：

1. 正規 OAuth 2.0 Authorization Code + PKCE（給 ChatGPT / 自訂連接器使用）
2. 靜態 `MCP_API_TOKEN`（給本機 smoke test / 既有自動化相容使用）

所有 `/mcp` 請求需帶 Bearer Token：

```
Authorization: Bearer <access_token>
```

### ChatGPT 自訂連接器填寫

| 欄位 | 值 |
|------|----|
| 連接器名稱 | `edgars mcp` |
| MCP 伺服器 URL | `https://mcp.whoasked.vip/mcp` |
| 驗證 | `OAuth` |
| Client ID | `handcraft-mcp` |
| Client Secret | `handcraft-mcp-client-secret` |
| 傳輸 | 可串流 HTTP |

OAuth discovery endpoints：

```text
https://mcp.whoasked.vip/.well-known/oauth-authorization-server
https://mcp.whoasked.vip/.well-known/oauth-protected-resource
```

此 MCP 使用 Authorization Code + PKCE S256。對外顯示的 connector / `serverInfo.name` 是 `edgars mcp`；OAuth `client_id` 仍保留 `handcraft-mcp`，避免既有授權設定被破壞。為了相容不允許空白 Client Secret 的 AI UI，預設手動 client secret 是 `handcraft-mcp-client-secret`；正式環境可用 `MCP_OAUTH_CLIENT_SECRET` 覆蓋。Dynamic client registration 端點為 `/register`，會核發 `client_id` 與 `client_secret`。

---

## 工具總覽（56 個）

### 🤖 AI 代理（7）

| 工具 | 說明 |
|------|------|
| `codex_agent` | 委派任務給 Codex AI（程式碼實作、檔案編輯） |
| `gemini_agent` | 委派任務給 Gemini CLI（快速通用任務） |
| `claude_code_agent` | 委派任務給 Claude Code（複雜重構、多檔操作） |
| `ollama_agent` | 委派任務給本地 Ollama 模型（離線可用） |
| `smart_agent` | 智慧選擇最適合的 agent 執行任務 |
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

### 🌐 瀏覽器（3）

| 工具 | 說明 |
|------|------|
| `browser_screenshot` | 對網頁截圖，存到 `.screenshots/` |
| `browser_get_text` | 擷取網頁純文字內容 |
| `browser_run_script` | 在網頁上執行 JavaScript |

> 需要 Playwright + Chromium：`playwright install chromium`

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
C:\Users\EdgarsTool\Projects\mcp-handcraft\reports
```

---

### 📋 Linear（3）

| 工具 | 說明 |
|------|------|
| `linear_issues` | 列出 issues（可篩選狀態/優先級） |
| `linear_create_issue` | 建立新 issue |
| `linear_update_issue` | 更新 issue 狀態或新增留言 |

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

### 🎬 MiniMax 媒體（8，需付費帳號）

| 工具 | 說明 |
|------|------|
| `mmx_image_generate` | 生成圖片 |
| `mmx_video_generate` | 生成影片 |
| `mmx_speech_synthesize` | 文字轉語音 |
| `mmx_music_generate` | 生成音樂 |
| `mmx_vision_describe` | 圖片描述 |
| `mmx_search_query` | MiniMax 搜尋 |
| `mmx_text_chat` | MiniMax 對話 |
| `mmx_quota_show` | 查看剩餘額度 |

---

### 📓 Obsidian Vault（13）

Vault 路徑：`D:\Edgar'sObsidianVault`

| 工具 | 說明 |
|------|------|
| `vault_read` | 讀取筆記內容 |
| `vault_write` | 建立或覆蓋筆記 |
| `vault_append` | 在筆記末尾附加內容 |
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
cd C:\Users\EdgarsTool\Projects\mcp-handcraft
doppler run -- python -m unittest test_server_http.py -v
```

---

## 環境變數（由 Doppler 管理）

| 變數 | 說明 |
|------|------|
| `MCP_API_TOKEN` | Bearer Token 認證 |
| `MCP_OAUTH_CLIENT_ID` | OAuth 預設 public client id（預設 `handcraft-mcp`） |
| `MCP_OAUTH_CLIENT_SECRET` | OAuth 預設 client secret（預設 `handcraft-mcp-client-secret`） |
| `MCP_OAUTH_AUTH_CODE_TTL_SECONDS` | OAuth 授權碼有效秒數（預設 600） |
| `MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS` | OAuth access token 有效秒數（預設 7776000） |
| `PERPLEXITY_API_KEY` | web_search 用 |
| `OPENAI_API_KEY` | 備用 |
| `LINEAR_API_KEY` | Linear issue 管理 |
| `NOTION_API_KEY` | Notion 讀取 |
| `TRACKTW_API_KEY` | TrackTW 物流查詢 |
| `MCP_AGENT_TIMEOUT_SECONDS` | Agent 等待上限（預設 300 秒） |
| `MCP_BASE_URL` | 公開 URL（預設 https://mcp.whoasked.vip） |

---

## 公開端點

```
https://mcp.whoasked.vip/mcp
```

透過 Cloudflare Tunnel 對外。本機重開機後需手動重啟 cloudflared。

### Hermes stdio proxy

Hermes 這類只會啟動 stdio MCP server 的 client，可改啟動：

```powershell
python .\hermes_stdio_proxy.py
```

預設會轉送到 `http://127.0.0.1:8765/mcp`。如果 HTTP endpoint 不在本機預設位置，可設定 `HERMES_HANDCRAFT_MCP_URL`。

### Package webhook

給 TrackTW / 包裹通知使用的 webhook URL：

```text
https://mcp.whoasked.vip/webhook/package
```

本機對應 endpoint 是：

```text
http://127.0.0.1:8765/webhook/package
```

這條不是 MCP endpoint。對方要「接 MCP」時給 `/mcp`；對方要「包裹 webhook」時給 `/webhook/package`。

### Linear webhook

給 Linear webhook 使用的 URL：

```text
https://mcp.whoasked.vip/webhook/linear
```

這條不是 MCP endpoint。對方要「接 Linear webhook」時給 `/webhook/linear`。

若 endpoint 需要 bearer token，設定 `HERMES_HANDCRAFT_MCP_TOKEN`；本檔不保存 token，也不要把 runtime log、`.screenshots/`、`__pycache__/` 或圖片檔 commit 進 repo。

---

## 相關連結

- Linear Project：WHO 系列 issues
- Agent-KB：`D:\Agent-KB`
- Vault：`D:\Edgar'sObsidianVault`
- Screenshots：`C:\Users\EdgarsTool\Projects\mcp-handcraft\.screenshots\`
