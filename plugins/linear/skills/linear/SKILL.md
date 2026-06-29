---
name: linear
description: Manage Linear workflows for the mcp-handcraft repo and Edgar's WHO issue flow. Use when Codex needs to read, create, update, summarize, or hand off Linear issues related to repo delivery, MCP health, webhook work, project tracking, or agent handoffs, especially when using the mcp-handcraft Linear tools `linear_issues`, `linear_create_issue`, and `linear_update_issue`.
---

# Linear

## Overview

Use this skill to keep Linear work tied to the current repo state instead of treating Linear as a separate inbox. Prefer small, traceable updates: read the repo and Agent-KB context first, then create or update only the issues needed for the active task.

## Entry Workflow

1. Read current context before touching Linear:
   - `G:\Agent-KB\DAILY\RECENT.md`
   - `G:\Agent-KB\DAILY\LEARNINGS.md`
   - `G:\Agent-KB\RULES.md`
   - `G:\Agent-KB\PLAYBOOKS\AGENT-SKILLS-SCAN-MAP.md`
   - `git status --short --branch`
2. Identify whether the user wants read-only review, a new issue, an issue update, or a handoff note.
3. Use read-only operations first. In mcp-handcraft, `linear_issues` is read-only; `linear_create_issue` and `linear_update_issue` change Linear.
4. For write operations, require a verified write flow: preflight read, minimal write, read-back verification, then a concise closeout.
5. For write operations, keep changes scoped to the active task. If the repo has unrelated dirty files, mention them and do not include them in the Linear update unless the user explicitly asks.
6. Summarize exactly what changed in Linear and what still needs human or follow-up agent action.

## Tool Map

Use the mcp-handcraft Linear tool names when available:

- `linear_issues`: list issues. Supports optional `state`, `limit`, and `assignee_me`.
- `linear_create_issue`: create an issue. Requires `title`; supports `description`, `team_name`, and `priority` where `0=none`, `1=urgent`, `2=high`, `3=medium`, `4=low`.
- `linear_update_issue`: update an issue by key such as `WHO-123`; supports `state` and `comment`.

If direct Linear MCP tools are available instead, map the same intent to their issue list/create/update/comment equivalents, but preserve this skill's workflow and safety rules.

## Common Tasks

### Triage Repo Delivery

1. Read `git status --short --branch` and the latest relevant README/OPS/test context.
2. List active Linear issues with `linear_issues`, usually with `assignee_me=true` or a small `limit`.
3. Match work to issue IDs such as `WHO-###`.
4. Report mismatches: branch without issue, issue without branch evidence, blocked auth, failed checks, or uncommitted changes.

### Create A Tracking Issue

Create an issue only when the task needs follow-up, handoff, or durable tracking. Use a title that names the behavior or delivery goal, not a vague activity.

Use this body shape:

```markdown
## Intent
What problem or delivery gap this issue tracks.

## Current Evidence
- Repo/branch:
- Files or commands checked:
- Relevant status:

## Scope
- In:
- Out:

## Verification
- How to confirm this is done:

## Risks
- Known risk or "None known":
```

### Update An Existing Issue

Before updating, confirm the issue key and read enough local context to avoid stale comments. Prefer one concise comment with:

- status now
- files or branch involved
- verification run or skipped
- blocker, risk, or next step

Do not mark an issue `Done` unless there is concrete verification or the user explicitly says it is done.

### Handoff To Another Agent

When preparing a Linear handoff, include:

- branch name
- changed files
- command output summary
- known unrelated dirty files
- exact next action
- forbidden areas from `G:\Agent-KB\RULES.md` if relevant

Keep handoffs actionable; avoid project history unless it changes the next action.

## Safety Rules

- Do not read, paste, or request secrets. If Linear auth or API keys are missing, say that `Edgars_secret` may contain the source and stop at a non-sensitive instruction.
- If Linear session/auth is expired, report the blocker and suggest re-auth; do not reset OAuth, rotate tokens, or edit secret storage automatically.
- Do not create broad new workstreams without an explicit user task or a clear existing WHO issue.
- Do not merge, force push, reset, deploy, delete, or move files as part of a Linear update.
- Treat `G:\Agent-KB` as source-of-truth context, not scratchpad output.
- Treat `[BLOCKED] ... Reason:` from mcp-handcraft as an authoritative failed write report. Do not claim Linear changed unless the tool reports read-back verification.

## Verified Write Closeout

When `linear_create_issue` or `linear_update_issue` succeeds through mcp-handcraft, expect the tool to confirm read-back verification. If it returns `[BLOCKED]`, report:

- target issue or title
- reason text from the tool
- what was attempted
- whether any partial write may need human inspection

## Final Response Shape

For Linear write operations, return:

- Status
- Linear Changes
- Files/Branch Context
- Verification
- Risks
- Next

For read-only triage, return findings first, then the recommended next Linear action.
