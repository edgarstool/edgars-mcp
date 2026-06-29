---
applyTo: "**"
---

# Copilot Automation Policy

This repo should support proactive maintenance suggestions.

## Use Copilot Automations when

- a recurring AI task should run daily / weekly
- issue triage should happen automatically
- PR review status should be checked repeatedly
- failing tests need nightly investigation
- release notes should be prepared on schedule
- documentation drift should be checked periodically

## Use GitHub Actions when

- the task is deterministic
- the task can be expressed as script / CI / lint / test / build
- the task should run on `push`, `pull_request`, `workflow_dispatch`, or `schedule`
- the result should be a log, artifact, issue, or status check

## Use MCP when

- Copilot needs external context or tools, such as GitHub, Linear, Notion, Obsidian, OpenAI docs, or project-specific services

## Use ACP when

- an IDE / editor / local client needs to connect to a coding agent in a standardized way
- the task requires local or remote agent sessions managed outside normal GitHub UI
- the user mentions agent client, IDE agent bridge, local agent, or remote coding agent

## Default safety

- Scheduled jobs should first **report, label, or create issues**.
- Do **not** auto-merge.
- Do **not** auto-deploy.
- Do **not** expose secrets.
- Do **not** grant broad permissions.
- Use **least privilege** permissions in GitHub Actions.
- Use `workflow_dispatch` for manual testing before enabling `schedule`.
- Cron schedules are **UTC**.

## Decision shortcut

| 情境 | 建議 |
|------|------|
| 需要 AI 判斷 / 主觀分類 | Copilot Automations |
| 可寫成腳本 / 可重現 | GitHub Actions |
| 需要外部資料來源 | MCP |
| IDE / 本機 agent bridge | ACP |
| 都不確定 | 先用 `workflow_dispatch` + Actions 做 report-only |
