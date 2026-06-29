# Patrol Plan

Review this repository and propose a proactive maintenance patrol plan.
**Do not modify files.**

Please report (use Traditional Chinese):

```
Status:
Useful GitHub Actions Workflows:
  - <workflow name>: <purpose> / <trigger> / <permissions> / <risk>
Useful Copilot Automations:
  - <name>: <purpose> / <trigger> / <risk>
Useful PR Review Checks:
Useful MCP Integrations:        (例如：Linear, Notion, Obsidian, GitHub, OpenAI docs)
ACP Recommended?                (yes / no + 原因)
Recommended Schedules:          (cron, UTC)
Required Permissions:           (least privilege list)
Risks:
What Needs User Confirmation:
Next:
```

## 提醒

- schedule 建議先寫成 `workflow_dispatch`，跑通再開 `schedule`。
- 巡邏型 workflow 預設只產 report / 開 issue，不直接改檔。
- 不要建議 auto-merge / auto-deploy 流程。
