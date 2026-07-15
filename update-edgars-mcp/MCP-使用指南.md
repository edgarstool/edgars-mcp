---
title: MCP 使用指南（mcp-handcraft）
created: 2026-07-04
tags: [mcp, 使用指南, edgars-tools]
---

# MCP 使用指南 — 怎麼用、怎麼接其他工具

> 白話版。你的 MCP 是「一個讓 AI 能操作你電腦與各種服務的統一入口」。

## 一、這是什麼、對外網址在哪
- 你的 MCP server（mcp-handcraft）把 70+ 個能力包成一個端點，任何支援 MCP 的 AI 都能連上來用。
- **對外網址：`https://mcp.edgars.tools/mcp`**（本機直連是 `http://127.0.0.1:8765/mcp`）。
- 授權：現在是「全綠」——Cloudflare Access 登入、或 Bearer token、或靜態 token，任一種有效就能連。

## 二、怎麼「使用」（讓 AI 連上來）
MCP 的運作方式是：**AI 客戶端（Claude、ChatGPT、Cursor…）當「客人」，連到你的 MCP server 這個「工具箱」**。
連上後，AI 就能呼叫你 server 裡的工具（讀寫檔案、跑 git、查 Notion、生圖…）。

### Claude Desktop
設定 → 連接器（Connectors）→ 新增自訂連接器 → 填 `https://mcp.edgars.tools/mcp`。
（授權會走 Cloudflare Access 或你發的 token。）

### ChatGPT（連接器 / Custom Connector）
設定 → Connectors → 新增 → 網址填 `https://mcp.edgars.tools/mcp`。
你 server 已內建給 ChatGPT 用的 OAuth，照畫面授權即可。

### Cursor / VS Code（開發工具）
在該工具的 MCP 設定檔加一段，指向你的端點或本機 stdio 入口（`server.py`）。
細節在 repo 的 `config/mcp.remote.example.json`、`config/mcp.local.example.json` 有範例。

## 三、怎麼「連結其他 SaaS」
你的 MCP **本身就是各種 SaaS 的橋樑**——它已經接了：
Notion、Linear、Obsidian、Warp、Cursor、Factory.ai、Cloudflare、Google（Gmail/Drive/Calendar）等。
所以「連其他 SaaS」有兩個方向：

1. **AI 透過你的 MCP 去操作 SaaS**（既有）：例如叫 AI「查 Notion 某頁」→ AI 呼叫你 server 的 `notion_search` 工具。
   要新增一個 SaaS，就在 server 裡加一個工具 + 該 SaaS 的 API 金鑰（放 Doppler，不寫進程式）。

2. **別的自動化平台（n8n / Make / Zapier）呼叫你的 MCP**：
   它們用 HTTP 打 `https://mcp.edgars.tools/mcp`，帶上 Bearer token 即可觸發工具。

> 金鑰規則：一律放 **Doppler / 1Password**，用環境變數注入，不要寫進程式或版控。

## 四、工具分類（約 70 個）
| 類別 | 例子 |
|---|---|
| 檔案系統 | 讀、寫、搬、刪、列目錄 |
| Git | 狀態、commit、分支、diff |
| 系統指令 | 跑 shell / PowerShell |
| 瀏覽器 | 自動化操作、抓網頁 |
| AI 代理委派 | codex / gemini / claude_code / smart agent |
| 媒體生成 | 免費圖片生成（`image_generate_free`）；MiniMax `mmx_*` 已封存 |
| 知識庫 | Obsidian、Notion（search / get_page） |
| 專案 | Linear（OAuth 委派） |
| 其他整合 | Warp、Cursor、Factory.ai、Cloudflare |

## 五、儀表板
現在有兩個檔，但角色不同：

1. **真正的即時控制台：`mcp-dashboard.py`**
   - 會在本機開 `http://127.0.0.1:8788/`
   - 即時讀：
     - `http://127.0.0.1:8765/health`
     - `https://mcp.edgars.tools/mcp`
     - `https://mcp.edgars.tools/.well-known/oauth-protected-resource`
     - Windows 服務 / process 狀態
     - `V:\projects\edgars-mcp\logs\` 的 log tail
   - 啟動方式：雙擊 `MCP-即時控制台.cmd`

2. **入口說明頁：`MCP-控制台.html`**
   - 這份現在不是狀態真相來源，只是入口頁
   - 用來快速開 `http://127.0.0.1:8788/`、看資料來源、看排錯順序

> 簡單講：**要看真實健康狀態，看 `mcp-dashboard.py` 跑出來的 live dashboard；不要再把 `MCP-控制台.html` 當成即時狀態頁。**

## 六、常見狀況
- **連不上/紅**：先確認 server 在跑（`/health`）、token 對不對、Cloudflare Tunnel 有沒有通。
- **重開機後要重新授權**：OAuth token 存記憶體，server 一重開就清空（見維護指南）。
- **要加新工具**：在 `server_http.py` 加一個 `TOOLS` 描述 + `handle_xxx` 函式 + 在 `handle_tools_call` 接上。
