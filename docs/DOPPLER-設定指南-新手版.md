---
lang: zh-TW
---

# Doppler 設定指南（新手版）

> 給德德用的：完全不用懂程式，照著做就好。

---

## 最快路徑（3 步）

1. 用瀏覽器打開 **[dashboard.doppler.com](https://dashboard.doppler.com)**，登入你的帳號。
2. 左邊點專案 **`handcraft-mcp`** → 上方選 **`prd`**（正式環境）。
3. 點 **「Add Secret」**（新增密碼），把下面表格裡**還沒填的每一列**都加進去（名稱要一字不差複製）。

加完後，重開 MCP server（關掉再跑 `run_http.cmd`）才會生效。

---

## Doppler 是什麼？

想像一個**雲端密碼保險箱**。

- 每個格子有兩個部分：**名稱**（標籤）和**值**（真正的密碼）。
- 程式啟動時，Doppler 會自動把這些密碼「餵」給 MCP server，不用寫在檔案裡、也不用在聊天裡貼給 AI。

**千萬不要**把密碼貼在 LINE、Discord、或跟 AI 聊天裡。只貼在 Doppler 網頁上就好。

---

## 「變數名稱」和「值」差在哪？

```
┌─────────────────────────────────────────────────────────┐
│  Doppler 畫面（示意）                                    │
├──────────────────┬──────────────────────────────────────┤
│  名稱（標籤）     │  值（密碼本體）                       │
│  貼在左邊欄位     │  貼在右邊欄位                         │
├──────────────────┼──────────────────────────────────────┤
│  WARP_API_KEY    │  wk-abc123xyz789...（很長一串）       │
│  CURSOR_API_KEY  │  key_xxxxxxxxxxxxxxxx...             │
│  MCP_API_TOKEN   │  你自己發明的一長串亂碼（見下方說明）   │
└──────────────────┴──────────────────────────────────────┘
```

- **名稱** = 標籤紙，程式靠這個名字去找密碼。**必須跟表格一模一樣**（大小寫、底線都要對）。
- **值** = 真正的密碼，從各服務網站複製過來（或自己發明，見 `MCP_API_TOKEN`）。

在 Doppler 新增時：

1. **Name** 欄 → 貼「變數名稱」
2. **Value** 欄 → 貼「值」（從別的網站複製來的那串）
3. 按 **Save**

---

## 目前 Doppler 裡有沒有？（只查名稱，不顯示密碼）

專案 `handcraft-mcp` / 設定 `prd`，截至 2026-06-29：

| 變數名稱 | 已經在 Doppler？ |
|----------|------------------|
| `MCP_API_TOKEN` | ✅ 已有（可跳過） |
| `LINEAR_API_KEY` | ✅ 已有（可跳過） |
| `LINEAR_CLIENT_ID` | ❌ **Hermes OAuth 要加**（見 [Linear-OAuth設定-新手版](./Linear-OAuth設定-新手版.md)） |
| `LINEAR_CLIENT_SECRET` | ❌ **Hermes OAuth 要加** |
| `LINEAR_WEBHOOK_SECRET` | 選填（開 Linear webhook 時再填） |
| `LINEAR_CLIENT_ID` | ❌ **還沒有，Hermes OAuth 用** |
| `LINEAR_CLIENT_SECRET` | ❌ **還沒有，Hermes OAuth 用** |
| `LINEAR_WEBHOOK_SECRET` | ❌ **還沒有，開 webhook 前需要** |
| `NOTION_API_KEY` | ✅ 已有（可跳過） |
| `OPENAI_API_KEY` | ✅ 已有（可跳過） |
| `PERPLEXITY_API_KEY` | ✅ 已有（可跳過） |
| `TRACKTW_API_KEY` | ✅ 已有（可跳過） |
| `MINIMAX_API_KEY` | 已封存（目前主 server 不使用，可忽略） |
| `WARP_API_KEY` | ❌ **還沒有，要加** |
| `CURSOR_API_KEY` | ❌ **還沒有，要加** |
| `FACTORY_API_KEY` | ❌ **還沒有，要加** |

---

## 完整密碼清單（照這張表填）

### 圖例

| 欄位 | 意思 |
|------|------|
| 必填 / 選填 | 沒填會怎樣 |
| 值長什麼樣子 | **假範例**，不是你的真密碼 |
| 去哪裡申請 | 網址 + 要按哪個按鈕 |

---

### ① 啟動必備

| 變數名稱（複製貼上） | 這是什麼 | 值長什麼樣子（假資料） | 去哪裡申請 | 必填？ |
|---------------------|----------|------------------------|------------|--------|
| `MCP_API_TOKEN` | MCP 自己的「大門鑰匙」。沒有它 server 開不起來。 | `hmc_8f3k2m9x7p1q4w6z0a5b2c8d1e4f7`（自己發明，至少 32 個英文數字） | **不用去外面申請。** 在 Doppler 按 **Generate** 自動產生，或自己敲一長串亂碼。 | **必填**（✅ 你已經有了，可跳過） |

---

### ② Warp / Cursor / Factory（你最近最需要的三個）

| 變數名稱（複製貼上） | 這是什麼 | 值長什麼樣子（假資料） | 去哪裡申請 | 必填？ |
|---------------------|----------|------------------------|------------|--------|
| `WARP_API_KEY` | 讓 AI 遙控 **Warp 雲端 Agent**（`warp_agent_run_create` 等工具） | `wk-AbCdEf1234567890GhIjKl`（一定以 `wk-` 開頭） | 1. 打開 [oz.warp.dev/settings](https://oz.warp.dev/settings)<br>2. 登入 Warp 帳號<br>3. 找到 **API Keys** 區塊<br>4. 按 **Create API Key** 或 **Generate**<br>5. 複製整串（只顯示一次，先複製再關視窗） | 選填（沒填 = Warp 那 3 個工具不能用）❌ **目前缺** |
| `CURSOR_API_KEY` | 讓 AI 遙控 **Cursor 雲端 Agent**（`cursor_agent_create` 等工具） | `key_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6` | 1. 打開 [cursor.com/dashboard](https://cursor.com/dashboard)<br>2. 登入 Cursor 帳號<br>3. 左側或上方找 **Integrations** 或 **API Keys**<br>4. 按 **Create API Key** / **New API Key**<br>5. 複製整串 | 選填（沒填 = Cursor 那 4 個工具不能用）❌ **目前缺** |
| `FACTORY_API_KEY` | 讓 AI 操作 **Factory.ai / Droid**（`factory_sessions_list` 等工具） | `fac_sk_live_1234567890abcdefghijklmnopqrstuvwxyz` | 1. 打開 [app.factory.ai/settings/api-keys](https://app.factory.ai/settings/api-keys)<br>2. 登入 Factory 帳號<br>3. 按 **Create API Key** 或 **Generate new key**<br>4. 複製整串 | 選填（沒填 = Factory 那 4 個工具不能用）❌ **目前缺** |

---

### ③ 其他功能用的密碼（大部分你已經有了）

| 變數名稱（複製貼上） | 這是什麼 | 值長什麼樣子（假資料） | 去哪裡申請 | 必填？ |
|---------------------|----------|------------------------|------------|--------|
| `PERPLEXITY_API_KEY` | 網路搜尋工具 `web_search` | `pplx-1234567890abcdefghijklmnopqrstuvwxyz` | 1. [perplexity.ai/settings/api](https://www.perplexity.ai/settings/api)<br>2. 按 **Generate API Key**<br>3. 複製 | 選填 ✅ 已有 |
| `LINEAR_API_KEY` | Linear 任務管理（開 issue、改狀態） | `lin_api_1234567890abcdefghijklmnopqrstuvwxyz` | 1. [linear.app/settings/api](https://linear.app/settings/api)<br>2. 按 **Create key**<br>3. 勾需要的權限 → **Create**<br>4. 複製 | 選填 ✅ 已有 |
| `LINEAR_CLIENT_ID` | Hermes Agent 的 Linear OAuth 應用 ID | `abc123def456` | 1. [linear.app/settings/api/applications/new](https://linear.app/settings/api/applications/new)<br>2. 建立 **Hermes Agent** 應用（或匯入 `config/linear-oauth-manifest.json`）<br>3. 複製 **Client ID** | 選填 ❌ **OAuth 用，目前缺** |
| `LINEAR_CLIENT_SECRET` | Hermes Agent OAuth 密鑰 | `secret_abcdef1234567890` | 同上，建立應用時複製 **Client Secret**（只顯示一次） | 選填 ❌ **OAuth 用，目前缺** |
| `LINEAR_WEBHOOK_SECRET` | 驗證 Linear webhook 簽章 | `whsec_abcdef1234567890` | Linear 應用設定頁的 **Webhook signing secret** | 選填 ❌ **開 webhook 前需要** |
| `NOTION_API_KEY` | 讀 Notion 頁面、搜尋 | `secret_1234567890abcdefghijklmnopqrstuvwxyz` | 1. [notion.so/my-integrations](https://www.notion.so/my-integrations)<br>2. **+ New integration**<br>3. 取名 → **Submit**<br>4. 複製 **Internal Integration Secret**<br>5. 到 Notion 各頁面按 **⋯ → Connections** 連結這個 integration | 選填 ✅ 已有 |
| `OPENAI_API_KEY` | 備用 AI（少數功能） | `sk-proj-1234567890abcdefghijklmnopqrstuvwxyz` | 1. [platform.openai.com/api-keys](https://platform.openai.com/api-keys)<br>2. **+ Create new secret key**<br>3. 複製 | 選填 ✅ 已有 |
| `TRACKTW_API_KEY` | 查台灣物流（黑貓、7-11 等） | `ttw_1234567890abcdefghijklmnopqrstuvwxyz` | 1. 打開 [track.tw](https://track.tw)<br>2. 登入 → 帳號 / API 設定<br>3. 產生 API Key 並複製 | 選填 ✅ 已有 |
| `MINIMAX_API_KEY` | 已封存的 MiniMax 媒體工具舊設定 | `eyJhbGciOi...` 或一長串英數 | MiniMax 官方後台 → API Keys | 目前可忽略 |

---

### ④ 進階設定（99% 情況不用動）

這些有內建預設值，**新手不用填**。只有進階調校才需要：

| 變數名稱 | 預設值 | 什麼時候才要改 |
|----------|--------|----------------|
| `MCP_PORT` | `8765` | 8765 被別的程式佔用時 |
| `MCP_BASE_URL` | `https://mcp.edgars.tools` | 換網域時 |
| `MCP_AGENT_TIMEOUT_SECONDS` | `300` | Agent 任務常逾時時調大 |
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama 不在本機預設位址時 |

如果你之後要讓 **遠端 Codex / Claude / Hermes** 走 Cloudflare Access 的機器身分，還會再多兩個秘密：

| 變數名稱 | 什麼時候才要加 |
|----------|----------------|
| `MCP_CF_ACCESS_CLIENT_ID` | 給遠端 agent 走 Cloudflare Access service token 時 |
| `MCP_CF_ACCESS_CLIENT_SECRET` | 給遠端 agent 走 Cloudflare Access service token 時 |

這兩個不是現在一定要填；只有你真的要讓**遠端 agent 正式接 public MCP**時才需要。

---

## 在 Doppler 網頁怎麼新增一筆？（圖文步驟）

以 `WARP_API_KEY` 為例，其他都一樣：

1. 打開 [dashboard.doppler.com](https://dashboard.doppler.com)
2. 點左邊 **Projects** → **handcraft-mcp**
3. 上方下拉選 **prd**
4. 點右上角 **Add Secret**（或 **+**）
5. **Name** 輸入：`WARP_API_KEY`（從表格複製，不要多空格）
6. **Value** 貼上：從 Warp 網站複製的那串（以 `wk-` 開頭）
7. 按 **Save**
8. **重開 MCP server**（關掉舊視窗，再雙擊 `run_http.cmd`）

---

## 常見問題

**Q：我填了，工具還是說 key 沒設？**  
→ 有沒有重開 server？Doppler 改完要重開才會讀到新值。

**Q：名稱打錯了怎麼辦？**  
→ 刪掉錯的那筆，重新新增，名稱必須一模一樣（例如 `warp_api_key` 是錯的，要是 `WARP_API_KEY`）。

**Q：值貼錯了 / 過期了？**  
→ 到原網站重新產生一把新 key，回 Doppler 編輯 Value 欄，存檔，重開 server。

**Q：要不要把密碼貼給 AI 幫我設定？**  
→ **不要。** 只在 Doppler 網頁貼。AI 不需要看到你的密碼。

**Q：`MCP_API_TOKEN` 跟 `CURSOR_API_KEY` 是同一把嗎？**  
→ **不是。** `MCP_API_TOKEN` 是你自己 MCP 大門的鑰匙；`CURSOR_API_KEY` 是 Cursor 官網發的，兩個分開填。

---

## 你現在只要做這 3 件事

1. 打開 Doppler → `handcraft-mcp` → `prd`
2. 新增 **`WARP_API_KEY`**、**`CURSOR_API_KEY`**、**`FACTORY_API_KEY`**（各去對應網站申請，貼到 Value）
3. 重開 `run_http.cmd`

其他密碼你已經有了，不用動。

---

## 相關文件

- 技術細節：[DOPPLER.md](../DOPPLER.md)
- 完整工具列表：[README.md](../README.md)
