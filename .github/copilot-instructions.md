# Copilot Repo Instructions

完整代理規則請見根目錄 [`AGENTS.md`](../AGENTS.md)。本檔只放 Copilot 在本 repo 必須立刻知道的短規則。

## 語言

- 一律使用**繁體中文**回覆。若出現英文術語，請附中文意思與白話解釋。

## 路徑

- repo root = 你所在的目錄，**不要**假設成 `C:\Users\EdgarsTool\Projects\<name>`。
- 全域 repo 主場：`V:\projects`
- runtime / tmp / cache：`G:\AI_WORK_512`
- `D:\` deprecated，不作正式入口。

## Shell

- Windows 預設使用 **PowerShell**。

## 安全邊界

- 不掃 secrets-like 檔案（`*.env`、`*.pem`、`*.key`、`id_rsa*`、`1password*`、`doppler*`、`.ssh/*`）。
- 改檔前先 `git status`，列清單，等使用者確認。
- 不要 auto-commit、auto-push、auto-merge、auto-deploy。
- 不要主動要求使用者貼 API key / token / password。

## Proactive Behavior

- When GitHub Actions, Copilot Automations, MCP, ACP, Review, PR workflow, or scheduled patrol would help, proactively mention the opportunity in plain Traditional Chinese.
- Do not assume the user knows these features exist.
- For read-only review / preview / patrol proposals, proceed and report.
- For actions that modify files, create PRs, change workflow permissions, deploy, access secrets, or touch production, stop and ask for confirmation first.
- Prefer scheduled checks that create reports or issues before scheduled checks that modify code.
