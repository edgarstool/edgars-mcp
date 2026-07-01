---
lang: zh-TW
---

# Cursor 雲端 Agent 預設 — 新手版（給德德）

> 最後更新：2026-06-29  
> 這份文件用**白話**說明：我們幫你預先建好的「遠端寫程式小幫手」是什麼、怎麼用。

---

## 這是什麼？

**Cursor 雲端 Agent** = Cursor 在雲端幫你開一台小電腦，讀你的 GitHub 專案、改程式、有時還能開 PR（合併請求）。

你可以把它想成：**「叫 Cursor 幫你寫程式那類功能」**，但它在 Cursor 的伺服器上跑，不用一直開著你自己的 Cursor 視窗。

我們已用 API 幫你建好 **5 個【預設】助手**，名字都有 `【預設】` 開頭，方便在清單裡認出來。

---

## 使用前：GitHub 要連好（很重要）

第一次用之前，請確認 Cursor 能讀寫你的 GitHub：

1. 打開 [cursor.com/dashboard](https://cursor.com/dashboard)
2. 登入你的 Cursor 帳號
3. 找 **Integrations**（整合）或 **GitHub**
4. 按 **Connect GitHub**，選 **Edgar-s-Tool** 組織，並允許讀寫 repo

若沒連好，Agent 會說找不到 branch 或沒權限。

---

## 怎麼打開、怎麼用？

### 方法一：網頁（最簡單）

1. 打開 **[cursor.com/agents](https://cursor.com/agents)**
2. 在清單找名字含 **`【預設】`** 的助手
3. 點進去 → 在對話框**用中文白話說你要它做什麼**
4. 等它跑完 → 到 GitHub 看有沒有新 branch / PR

### 方法二：Cursor 桌面版

1. 開 Cursor
2. 在 Agent 輸入框上方，模式選 **Cloud**（雲端）
3. 選已有的 Agent，或從 Agents 頁面連過去

### 方法三：透過 ChatGPT / 本機 MCP（進階）

若 ChatGPT 已連你的 **handcraft MCP**，可以請 AI 代叫 `cursor_agent_create` 或對既有 Agent 下指令。  
一般日常用 **方法一** 就夠了。

---

## 已建好的 5 個【預設】助手

| 名字 | 綁哪個 GitHub 專案 | 白話：平常請它做什麼 |
|------|-------------------|---------------------|
| **【預設】mcp-handcraft 維護助手** | [Edgar-s-Tool/mcp-handcraft](https://github.com/Edgar-s-Tool/mcp-handcraft)（分支 `master`） | 維護你的 MCP 大門（server、文件、腳本）。例：「幫我看 README 有沒有過期」「加一個新工具說明」 |
| **【預設】通用 Bug 修復助手** | 同上 mcp-handcraft | 你描述 bug，它幫查、修、跑測試。例：「某個 MCP 工具回錯誤，幫我修」 |
| **【預設】Agent-KB 知識庫助手** | [Edgar-s-Tool/Agent-KB](https://github.com/Edgar-s-Tool/Agent-KB)（`master`） | 整理筆記、補文件、搜尋主題。例：「幫我把這段整理成一篇 KB 條目」 |
| **【預設】linear-orchestrator 助手** | [Edgar-s-Tool/linear-orchestrator](https://github.com/Edgar-s-Tool/linear-orchestrator)（`main`） | Linear 任務編排相關。例：「解釋這 repo 怎麼跟 Linear 連動」 |
| **【預設】Cloudflare 骨架助手** | [Edgar-s-Tool/edgars-cf-workspace](https://github.com/Edgar-s-Tool/edgars-cf-workspace)（`master`） | Workers、wrangler、D1/KV 文件與部署腳本（**不要未確認就 deploy 正式環境**） |

### 直接連結（點開就能用）

- [mcp-handcraft 維護助手](https://cursor.com/agents/bc-0e762eb6-ca29-4765-b182-50dfb32cb699)
- [通用 Bug 修復助手](https://cursor.com/agents/bc-4e14fe85-530f-47b5-bf68-6b4c0e94f6e6)
- [Agent-KB 知識庫助手](https://cursor.com/agents/bc-8792d0c0-ec7e-4bf9-91ec-aee06177df69)
- [linear-orchestrator 助手](https://cursor.com/agents/bc-bc0d2d33-1a1d-4244-89df-1cbd56045a8a)
- [Cloudflare 骨架助手](https://cursor.com/agents/bc-887de86e-49b1-4f5e-bf0d-604816986f48)

第一次啟動時，每個助手會先**認識專案、用中文說明能幫什麼**，**不會亂改檔案**（我們有特別這樣下指令）。

---

## Linear OAuth（Hermes Agent）

Hermes 跟 Linear 的 OAuth 接線說明在 **[Linear-OAuth設定-新手版](./Linear-OAuth設定-新手版.md)**。

---

## 安全提醒（請德德知道就好）

這些助手**有能力改 GitHub 上的程式**。我們有設規則（改前先報告、不亂 deploy），但請你：

- **不要**在未確認前讓它改 Cloudflare DNS、正式 production、或 force-push
- 改完到 **GitHub 看 diff** 再決定要不要合併
- 機密（API key）永遠不要寫進 repo；用 Doppler / Cursor Secrets

---

## 常見問題

**Q：清單裡有很多舊的 Agent，要刪嗎？**  
→ 舊的可以 Archive；找 **`【預設】`** 開頭的就是這次幫你建好的。

**Q：它會自動幫我 commit 嗎？**  
→ 視任務而定。預設助手第一次只做「認識專案」。之後你下任務，它可能開新 branch；是否開 PR 要看你怎麼說。

**Q：ChatGPT 能叫這些 Agent 嗎？**  
→ 可以，若 MCP 有連且設了 `CURSOR_API_KEY`；日常用 cursor.com/agents 最直覺。

**Q：為什麼之前 `cursor_agents_list` 顯示空的？**  
→ API 回傳欄位叫 `items`，程式已修正，現在應能列出 Agent。

---

## 需要幫忙時怎麼說（範例）

對 **mcp-handcraft 維護助手**：

> 「請讀 README，用白話告訴我這個 MCP 現在有哪些工具，不要改任何檔案。」

對 **Bug 修復助手**：

> 「test_server_http 裡某某測試失敗，幫我找出原因並用最小改動修好，改前先列出要改哪些檔案。」

對 **Agent-KB 助手**：

> 「幫我在知識庫找跟 Cloudflare Workers 有關的筆記，整理成一段摘要。」

---

## 相關連結

- [Cursor 雲端 Agent 說明](https://cursor.com/docs/cloud-agent)
- [Cursor Agents 網頁](https://cursor.com/agents)
- [Cursor Dashboard（API Key / GitHub）](https://cursor.com/dashboard)
- 本 repo 的 [DOPPLER 設定指南](./DOPPLER-設定指南-新手版.md)（含 `CURSOR_API_KEY` 怎麼填）
