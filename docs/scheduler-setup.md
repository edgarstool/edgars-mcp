# Windows 工作排程器 — MCP 自動巡邏（技術版）

本文件說明 `install-patrol-scheduler.ps1` 註冊的排程任務。  
給德德看的白話版請看 **[自動巡邏-新手版.md](自動巡邏-新手版.md)**。

## 快速安裝

```powershell
cd V:\projects\mcp-handcraft
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-patrol-scheduler.ps1
```

- 需要**系統管理員**時：在 PowerShell 圖示按右鍵 →「以系統管理員身分執行」，再跑上面指令。
- 預覽不實際安裝：`.\scripts\install-patrol-scheduler.ps1 -WhatIf`
- 移除排程：`.\scripts\install-patrol-scheduler.ps1 -Uninstall`

## 任務一覽

| 任務名稱 | 路徑 | 頻率 | 執行腳本 | 行為 |
|---------|------|------|---------|------|
| MCP-HealthCheck | `\Edgars\MCP-HealthCheck` | 每 5 分鐘 | `patrol-healthcheck.ps1` | 呼叫 `check-mcp-health.ps1`；**絕不重啟** |
| MCP-AutoRecover | `\Edgars\MCP-AutoRecover` | 每 15 分鐘 | `patrol-auto-recover.ps1` | 連續失敗 ≥3 次才 `restart-mcp.ps1`；`:8645` 沒在跑就啟動 orchestrator |
| MCP-Maintain-Daily | `\Edgars\MCP-Maintain-Daily` | 每天 04:00 | `patrol-maintain-daily.ps1` | `maintain-mcp.ps1 -RestartIfUnhealthy` |
| MCP-LoginStart | `\Edgars\MCP-LoginStart` | 使用者登入 | `patrol-login-start.ps1` | `start-handcraft-http-at-login.ps1` + orchestrator 檢查 |

## 日誌路徑

| 類型 | 路徑 |
|------|------|
| 巡邏日誌 | `V:\projects\mcp-handcraft\logs\patrol-*.log`（依日期分檔） |
| 健康檢查詳細 | `V:\projects\mcp-handcraft\logs\healthcheck-*.log` |
| 即時健康摘要 | `G:\AI_WORK_512\run\mcp-handcraft\healthcheck-summary.json` |
| 連續失敗計數 | `G:\AI_WORK_512\run\mcp-handcraft\consecutive-failures.json` |

## 驗證排程有在跑

```powershell
Get-ScheduledTask -TaskPath \Edgars\ | Format-Table TaskName, State

# 手動跑一次健康檢查（不經排程器）
cd V:\projects\mcp-handcraft
.\scripts\patrol-healthcheck.ps1

# 看今天的巡邏日誌
Get-Content .\logs\patrol-healthcheck-$(Get-Date -Format yyyyMMdd).log -Tail 20
```

## 與其他自動化方案

- **主要方案**：本機 Windows 工作排程器（不依賴 Cursor / AI 在線）
- **未來可選**：Cursor Automations、GitHub Copilot Automations（見 `edgars-cf-workspace` 的 [COPILOT-AUTOMATIONS.md](https://github.com/Edgar-s-Tool/edgars-cf-workspace/blob/main/.github/COPILOT-AUTOMATIONS.md)）— 適合 repo 巡檢、issue 分類，**不取代**本機 MCP 常駐修復

## 疑難排解

| 症狀 | 可能原因 | 處理 |
|------|---------|------|
| 安裝腳本說缺少 `check-mcp-health.ps1` | repo 不完整 | `git pull` 或確認 `V:\projects\mcp-handcraft` 路徑 |
| 任務狀態 Disabled | 被手動停用 | 工作排程器 → 右鍵 → 啟用 |
| 日誌沒更新 | 電腦睡眠 / 未登入 | 登入並保持開機；LoginStart 會在登入時補啟動 |
| 一直重啟 MCP | 連續失敗未清除 | 看 `consecutive-failures.json`；手動跑桌面「檢測MCP」捷徑診斷 |
