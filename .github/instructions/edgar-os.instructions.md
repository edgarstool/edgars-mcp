---
applyTo: "**"
---

# EDGAR-OS v1.0 路徑與環境規則

本 repo 屬於 EDGAR-OS v1.0 總地形。所有 agent 進入時請遵循以下 canonical rules。

## 總地形

- 本機 = 基地
- Cloudflare = 外網城門
- `edgars.tools` = 工具基礎設施主網域
- `whoasked.vip` = 產品網域
- Google Workspace = 身份與文件層
- Notion = 人類控制台
- VPS = 24/7 小後端
- Agent-KB = agent 規則母本
- Obsidian = 人類長期知識庫

## Canonical Path

| 用途 | Canonical | Physical / fallback |
|------|-----------|----------------------|
| Windows 使用者 / agent 設定層 | `C:\Users\EdgarsTool` | — |
| repo / project 實作主場 | `V:\projects` | — |
| runtime / cache / tmp / heavy storage | `G:\AI_WORK_512` | — |
| Agent-KB | `G:\Agent-KB` | `G:\AgentKB\Agent-KB` |
| Obsidian | `G:\Obsidian\Edgar'sObsidianVault` | `G:\AgentKB\Obsidian\Edgar'sObsidianVault` |

## Deprecated

- `D:\` — 不作正式入口，不要寫入新檔案、不要當任何入口路徑使用。
- `C:\Users\EdgarsTool\Projects\<name>` — 不是 repo 主場，請改用 `V:\projects\<name>`。

## 進入本機任務時優先讀

若具備本機檔案存取能力：

1. `G:\Agent-KB\DAILY\RECENT.md`
2. `G:\Agent-KB\DAILY\LEARNINGS.md`
3. `G:\Agent-KB\RULES.md`
4. `G:\Agent-KB\PLAYBOOKS\AGENT-SKILLS-SCAN-MAP.md`

若 canonical path 不存在，fallback 到 `G:\AgentKB\Agent-KB\...` 對應位置。

若無法直接讀本機，**明說限制**，不要假裝已讀。

## Cloudflare / 網域

- `edgars.tools` 子網：`www`、`docs`、`status`、`hooks`、`api`、`mcp`、`auth`、`kb`、`lab`、`admin`
- `whoasked.vip` 子網：`www`、`app`、`api`、`docs`、`status`、`admin`
- `hooks.edgars.tools` = unified webhook inbox
- `mcp.edgars.tools/mcp` = MCP endpoint（必須有 Access / auth / network boundary）

## Secrets 規則

不要主動要求使用者貼任何 secret。只列出需要的 **secret 名稱** 與建議放置位置：

- 1Password
- Doppler
- Cloudflare Secrets
- Google Secret Manager
- VPS env injection
