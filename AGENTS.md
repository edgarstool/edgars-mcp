# AGENTS.md

本文件給 GitHub Copilot coding agent、OpenAI Codex、Claude Code、其他 coding agent 共用。請優先閱讀。

## 溝通語言（強制）

- 不論使用者用何種語言提問，一律以**繁體中文**回覆。
- 技術／研究類專有名詞（例如 `snapshot`、`build`、`OAuth`、`MCP`）可保留英文原文，但必須在後面附上簡短中文說明。使用者非資工（CS，Computer Science）背景、英文閱讀吃力。
- 盡量避免艱深術語；必要時用生活化的比喻解釋。

## 使用者身份

- 日常稱呼：德德
- 正式身份：王世鈞（Edgar）
- 舊名稱 / 舊暱稱 / 舊專案稱呼皆為 deprecated alias，不要優先沿用。
- 不要把使用者身份綁定到任何單一 AI、agent、小隊或工具。

## Repo 與作業環境

- 本 repo 的 root = 你目前所在的 repo 目錄。
- **不要**把 repo root 假設成 `C:\Users\EdgarsTool\Projects\<name>`。所有 repo 主場一律在 `V:\projects\<name>`。
- 全域 repo 主場：`V:\projects`
- runtime / cache / tmp / heavy storage 主場：`G:\AI_WORK_512`
- Agent-KB canonical path：`G:\Agent-KB`（physical fallback：`G:\AgentKB\Agent-KB`）
- Obsidian canonical path：`G:\Obsidian\Edgar'sObsidianVault`（physical fallback：`G:\AgentKB\Obsidian\Edgar'sObsidianVault`）
- `D:\` 是 deprecated，不作正式入口。

## Shell 預設

- Windows 操作預設使用 **PowerShell**。
- 不要預設 bash / zsh，除非任務明確需要 WSL / Linux / VPS。

## 禁止事項

- 不要掃描 secrets-like path（`*.env`、`*.pem`、`*.pfx`、`*.key`、`id_rsa*`、`1password*`、`doppler*`、`.ssh/*` 等）。
- 不要主動要求使用者貼 API key / token / password / private key / OAuth secret。
- 不要修改 production 設定（Cloudflare / Google Workspace / Notion 正式設定 / 任何 DNS）未經確認。
- 不要 force-push、reset、rebase 主幹未經確認。
- 不要 auto-merge、auto-deploy。

## 改檔流程（強制）

1. 改檔前先 `git status` 與 `git diff`，回報目前 working tree 狀態。
2. 列出將要新增 / 修改 / 刪除的檔案清單。
3. 等使用者確認後再執行。
4. commit / push / 開 PR 前必須再次回報。
5. 若目標檔案已存在且須覆蓋，先 backup（`<file>.bak.<timestamp>`）或產生 merge proposal。

## Linear 任務收尾（強制）

每項有意義的任務結束後，必須先處理 Linear，再跟使用者說完成／卡住：

1. **完成**：對應 issue 寫清做了什麼、驗證結果；沒有就在 **Edgar's Tool** 開一張；狀態改 **Done**。
2. **未完成／阻塞**：同一 issue 寫卡點與已試過的事；狀態改 **Blocked**（或 In Progress + `blocked`）；**另開求助 issue**，內容要夠讓 cloud agent／其他 agent 接手。
3. 回報使用者時附 Linear 連結。不要把 secrets 寫進 Linear。
4. 細節見 `.cursor/rules/linear-task-closeout.mdc`。

## 預設輸出格式

```
Status:
Files Changed:
What Changed:
Verification:
Known Limits:
Risks:
Next:
```

## Proactive Patrol / 主動巡邏規則

你應主動提醒使用者以下功能何時可用，但**不得未確認就執行高風險操作**。

可主動建議的非互動式任務：

- 每日 / 每週 repo health check
- dependency freshness check（依賴更新檢查）
- failing tests triage（測試失敗初步判讀）
- lint / typecheck / build 狀態檢查
- stale TODO / FIXME 巡檢
- README / docs drift check（文件是否落後程式碼）
- issue triage（issue 分類）
- PR review（PR 風險審查）
- release note draft（發版摘要草稿）
- secret-like filename check（疑似 secrets 檔名檢查，**只看檔名不開檔**）
- generated files pollution check（產物是否混進 source tree）
- EDGAR-OS path compliance check（是否錯用 `C:\Users\EdgarsTool\Projects` 或 `D:\`）

提醒時請使用下列格式：

```
可用功能：
建議：
原因：
風險：
是否需要使用者確認：
下一步：
```

## 相關文件

- `.github/copilot-instructions.md` — Copilot repo-wide instructions
- `.github/instructions/edgar-os.instructions.md` — EDGAR-OS 路徑與環境規則
- `.github/instructions/powershell-windows.instructions.md` — Windows / PowerShell 任務規則
- `.github/instructions/copilot-automation-policy.instructions.md` — Automation / Actions / MCP / ACP 判斷
- `.github/prompts/` — 各種非互動式任務 prompt
- `.github/COPILOT-AUTOMATIONS.md` — 建議建立的 Copilot Automations 清單
