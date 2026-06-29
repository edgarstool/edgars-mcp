# Copilot Automations 建議清單

本檔列出本 repo 建議建立的 Copilot Automations 與判斷時機。所有 Automation **不要直接 auto-merge / auto-deploy**，先做 report 或 issue。

---

## Suggested Copilot Automations

### Daily Issue Triage
- **用途**：每天整理新 issue，標記 `bug` / `enhancement` / `question`。
- **Trigger**：daily schedule 或 issue created。
- **風險**：可能誤分類。
- **需確認**：是。

### Weekly Repo Patrol
- **用途**：每週檢查 README、測試、依賴、TODO / FIXME、workflow 狀態。
- **Trigger**：weekly schedule。
- **風險**：可能產生噪音 issue。
- **需確認**：是。

### Nightly Failing Test Investigation
- **用途**：夜間檢查 `main` / `master` 的 failing tests，提出修復 PR 草稿。
- **Trigger**：daily schedule。
- **風險**：可能產生低品質 PR。
- **需確認**：是。

### PR Review Assistant
- **用途**：PR opened / synchronized 時做風險審查（依 `.github/prompts/pr-review.prompt.md`）。
- **Trigger**：`pull_request` opened / synchronized。
- **風險**：可能評論過多。
- **需確認**：是。

### Release Notes Draft
- **用途**：每週或每次 release 前草擬 changelog。
- **Trigger**：weekly schedule 或 release branch event。
- **風險**：摘要可能漏內容。
- **需確認**：是。

---

## When to use GitHub Actions vs Copilot Automations

**GitHub Actions**：
適合 deterministic / 可腳本化任務，例如 test、lint、build、掃 TODO、產 report、依賴更新檢查、archive、cron-based health check。

**Copilot Automations**：
適合 **AI 判斷型** 任務，例如 issue triage、文件落差判斷、PR 風險審查、測試失敗原因研判、release note 草稿、跨檔影響評估。

**ACP**（Agent Client Protocol）：
適合 IDE / editor / local client 需要連接 coding agent 的情境。**不是每個 repo 都必須啟用**；只在 repo 會被多種 client（VS Code、JetBrains、本機 agent bridge）以 agent 模式存取時才導入。

**MCP**（Model Context Protocol）：
適合 Copilot 需要外部工具或資料來源，例如 Linear、Notion、Obsidian、OpenAI docs、GitHub API、Cloudflare API、Doppler、1Password。

---

## 啟用順序建議

1. 先用 `.github/workflows/repo-patrol.yml.template` 改名啟用，跑 `workflow_dispatch` 一次。
2. 跑通後再加入 `schedule`。
3. 確認 schedule 正常產 report 後，再考慮接 Copilot Automation 做 AI 判斷。
4. PR Review Assistant 最後上，避免新 repo 還沒穩就被機器人灌評論。
