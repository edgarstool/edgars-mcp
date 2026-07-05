---
lang: zh-TW
---

# Linear OAuth × Hermes Agent — 新手版（給德德）

> 最後更新：2026-06-30  
> 這份文件告訴你：**Linear 的「Hermes Agent」App 要怎麼接好**，你只要照步驟點、貼密碼就好。
>
> **硬護欄：OAuth / authorize / callback / status 全都在 `mcp.edgars.tools`；Linear Agent webhook 走 `webhooks.edgars.tools`；`hooks.edgars.tools` 是另一條 Worker inbox。**

---

## 這是什麼？（白話）

Linear 有一種 **OAuth App**（授權應用程式），讓 Hermes 可以：

- 以「App 身分」讀寫 issue、留言
- 參與 **Agent Session**（@Hermes 時自動派工）

我們已經在 **mcp.edgars.tools** 上準備好：

| 網址 | 用途 |
|------|------|
| `https://mcp.edgars.tools/linear/oauth/authorize` | 你點這裡 → 跳去 Linear 登入授權 |
| `https://mcp.edgars.tools/linear/oauth/callback` | Linear 授權完跳回來（不用手動開） |
| `https://mcp.edgars.tools/linear/oauth/status` | 檢查有沒有接成功（看 JSON） |

Webhook（事件通知）在 manifest 裡是 **關閉的**（`enabled: false`）。  
目前 Hermes 實際收 webhook 走的是 **webhooks.edgars.tools**（本機 tunnel → Windows `:8645`）。  
**硬護欄：`webhooks.edgars.tools` 是 gateway ingress；`hooks.edgars.tools` 是 Cloudflare Worker inbox，不要混填。**

---

## 你現在只要做這 4 步

### 步驟 1：在 Linear 建立 / 確認 OAuth App

1. 用瀏覽器打開 **[linear.app/settings/api](https://linear.app/settings/api)**（或 Workspace → Settings → API → OAuth applications）
2. 找到 **Hermes Agent**，或按 **New OAuth application**
3. 確認這些欄位（必須一模一樣）：

| 欄位 | 填什麼 |
|------|--------|
| Application name | `Hermes Agent` |
| Developer name | `Edgar AI Guild` |
| Redirect URI | `https://mcp.edgars.tools/linear/oauth/callback` |
| Homepage / Client URI | `https://github.com/Edgars-tool/hermes-agent` |

4. 儲存後，複製 **Client ID** 和 **Client Secret**（只顯示一次的那串）

> **不要**把 Client Secret 貼在聊天、LINE、Discord。只貼到 Doppler。

---

### 步驟 2：把密碼貼進 Doppler

1. 打開 **[dashboard.doppler.com](https://dashboard.doppler.com)**
2. 左邊選專案 **`handcraft-mcp`** → 上方選 **`prd`**
3. 按 **Add Secret**，新增下面每一列（名稱要一字不差）：

| 名稱（貼左邊） | 值（貼右邊） |
|----------------|--------------|
| `LINEAR_CLIENT_ID` | 從 Linear 複製的 Client ID |
| `LINEAR_CLIENT_SECRET` | 從 Linear 複製的 Client Secret |
| `LINEAR_WEBHOOK_SECRET` | 若 Linear App 有 Signing secret 再填；**webhook 還沒開可以先跳過** |

`LINEAR_API_KEY` **你已經有了**，不用動。

4. 存檔後，**重開 MCP**（見步驟 3）

---

### 步驟 3：重開 MCP，然後授權

1. 在 Cursor 或 PowerShell 執行（或請 AI 幫你跑）：
   ```powershell
   cd V:\projects\edgars-mcp
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1 -Force
   ```
2. 用瀏覽器打開：**[https://mcp.edgars.tools/linear/oauth/authorize](https://mcp.edgars.tools/linear/oauth/authorize)**
3. Linear 會問你是否允許 → 按 **Authorize** / 允許
4. 成功會看到綠色標題：**「Hermes Agent × Linear 授權成功」** → 可以關分頁

若失敗：

- 先看 **[https://mcp.edgars.tools/linear/oauth/status](https://mcp.edgars.tools/linear/oauth/status)**  
  - `configured: true` = Doppler 有 Client ID/Secret  
  - `token_present: true` = 授權成功
- 若 `configured: false` → 回到步驟 2 檢查 Doppler 名稱是否打錯

---

### 步驟 4：（選做）在 Linear 安裝 App 到你的工作區

1. 在 Linear OAuth App 頁面，找 **Install** 或分享安裝連結
2. 選你的工作區（例如 Edgar AI Guild）
3. 確認 Hermes 出現在成員 / App 列表裡

Webhook **先不要開**（manifest 裡 `enabled: false`）。要開時再跟 AI 說。

---

## Doppler 變數速查

| 變數 | 必填？ | 用途 |
|------|--------|------|
| `LINEAR_API_KEY` | ✅ 已有 | MCP 工具直接叫 Linear API（個人 key） |
| `LINEAR_CLIENT_ID` | ✅ 要加 | OAuth App 身分 |
| `LINEAR_CLIENT_SECRET` | ✅ 要加 | OAuth App 密碼 |
| `LINEAR_WEBHOOK_SECRET` | 選填 | 驗證 Linear webhook 簽章（開 webhook 時才需要） |
| `LINEAR_OAUTH_REDIRECT_URI` | 選填 | 預設已是 `https://mcp.edgars.tools/linear/oauth/callback` |
| `LINEAR_OAUTH_SCOPES` | 選填 | 預設 `read,write,app:assignable,app:mentionable` |

---

## 相關檔案（給 AI 看，你可以跳過）

- Manifest 備份：`config/linear-oauth-manifest.json`
- OAuth token 存本機：`config/linear-oauth-token.json`（**不會** commit 到 GitHub）
- Hermes webhook 現況：`V:\projects\cloudflared\HERMES-WEBHOOK.md`

---

## 常見問題

**Q：authorize 頁面說 not_configured？**  
→ Doppler 還沒加 `LINEAR_CLIENT_ID` / `LINEAR_CLIENT_SECRET`，或 MCP 沒重開。

**Q：Linear 顯示「Hermes Agent already installed」，只有 Cancel / Manage，沒有 Authorize？**  
→ 這是 Linear 的正常行為：App **6/24 已裝進工作區**，但 MCP **本機還沒存 token**（`token_present: false`）。  
→ **請照這條路走（唯一可靠）：**

1. 打開 **[linear.app/settings/applications](https://linear.app/settings/applications)**（或 Settings → Installed applications）
2. 找到 **Hermes Agent** → 按 **Manage**
3. 按 **Revoke access**（撤銷存取 / 解除安裝）
4. 用瀏覽器重新開：**[https://mcp.edgars.tools/linear/oauth/authorize](https://mcp.edgars.tools/linear/oauth/authorize)**
5. 這次應出現 **Install** 或 **Authorize** → 按下去
6. 看到「授權成功」後，確認 **[status](https://mcp.edgars.tools/linear/oauth/status)** 的 `token_present` 變成 `true`

> 我們已在授權網址加上 `prompt=consent`；若仍卡在 already installed，**一定要先做 Revoke**。

**Q：不想用瀏覽器，能自動拿 token 嗎？**  
→ 可以，但要在 Linear OAuth App 設定裡**開啟 Client credentials tokens**（建立/編輯 Hermes Agent 時的開關）。  
→ 開好後，瀏覽器打開：**[https://mcp.edgars.tools/linear/oauth/bootstrap](https://mcp.edgars.tools/linear/oauth/bootstrap)**  
→ 成功會回 JSON `"ok": true`；再查 status 應為 `token_present: true`。

**Q：callback 說 state 無效？**  
→ 授權連結過期（10 分鐘）。重新從 `/linear/oauth/authorize` 開始。

**Q：webhooks.edgars.tools 跟 mcp.edgars.tools/webhook/linear 差在哪？**  
→ **webhooks.edgars.tools** 是 Hermes Agent 正式 webhook（tunnel → linear-orchestrator）。**mcp.edgars.tools/webhook/linear** 只記 log，不會回 Linear。

**Q：我要開 webhook 怎麼辦？**  
→ 先確認 Hermes gateway 在跑，再跟 AI 說「要開 Linear webhook」；會另外給你步驟，不會偷偷改 production。

---

## 相關連結

- [Doppler 設定指南](./DOPPLER-設定指南-新手版.md)
- [Cursor 雲端 Agent 預設](./Cursor雲端Agent預設-新手版.md)
- [Linear OAuth 官方文件](https://linear.app/developers/oauth-2-0-authentication)
