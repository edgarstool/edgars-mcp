# Scheduler Setup — MCP 服務穩定性監控

本文件說明如何在 Windows Task Scheduler（工作排程器）設定三個自動化工作，完成 MCP 服務穩定性監控閉環。

---

## 前置條件

| 項目 | 說明 |
|------|------|
| Repo 路徑 | `V:\projects\mcp-handcraft`（或 `G:\AI_WORK_512\repos\mcp-handcraft`） |
| Runtime 路徑 | `G:\AI_WORK_512\run\mcp-handcraft\` |
| PowerShell | Windows PowerShell 5.1 或 PowerShell 7+ |
| 執行原則 | `-ExecutionPolicy Bypass`（Task 層指定，不改全域） |
| 帳號 | 以擁有 `V:\`、`G:\` 讀寫權限的使用者帳號執行 |

---

## 三個工作總覽

| 工作名稱 | 觸發頻率 | 腳本 | 說明 |
|----------|----------|------|------|
| `MCP_HealthCheck` | 每 5 分鐘 | `check-mcp-health.ps1` | 5 層 cascade 健康檢查，JSON+log 輸出 |
| `MCP_HourlyRestart` | 每小時 | `restart-mcp.ps1` | 預防性重啟（停→等→啟） |
| `MCP_DailyReport` | 每日 08:00 | `Invoke-DailyReport.ps1`（見附件） | 匯總前 24 小時 healthcheck-summary.json 記錄 |

---

## 工作 1：MCP_HealthCheck（每 5 分鐘）

### Task Scheduler GUI 步驟

1. 開啟「工作排程器」（`taskschd.msc`）
2. 右側 → **建立工作**（Create Task，非「建立基本工作」）
3. **一般（General）** 分頁：
   - 名稱：`MCP_HealthCheck`
   - 描述：`每 5 分鐘執行 MCP 5 層健康檢查`
   - 選取「**不論使用者是否登入都要執行**」
   - 勾選「**以最高權限執行**」（Run with highest privileges）
4. **觸發程序（Triggers）** 分頁 → 新增：
   - 開始工作：**依排程**
   - 設定：**每天**
   - 重複工作每：`5 分鐘`，持續時間：`無限期`
   - 勾選「啟用」
5. **動作（Actions）** 分頁 → 新增：
   - 動作：**啟動程式**
   - 程式：`powershell.exe`
   - 引數：
     ```
     -NoProfile -ExecutionPolicy Bypass -File "V:\projects\mcp-handcraft\scripts\check-mcp-health.ps1"
     ```
   - 起始位置：`V:\projects\mcp-handcraft`
6. **條件（Conditions）** 分頁：
   - 取消勾選「只有在電腦使用 AC 電源時才啟動此工作」（若為桌機可保留）
7. **設定（Settings）** 分頁：
   - 勾選「如果工作失敗，依下列頻率重新啟動」：每 `1 分鐘`，最多 `3` 次
   - 勾選「如果要求的工作已在執行中，下列規則適用」→ **不要啟動新執行個體**
8. 按 **確定** → 輸入帳號密碼

### PowerShell 一鍵建立（以系統管理員執行）

```powershell
$repoRoot  = "V:\projects\mcp-handcraft"
$script    = Join-Path $repoRoot "scripts\check-mcp-health.ps1"
$action    = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repoRoot

$trigger   = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 5) -Once -At (Get-Date)
$settings  = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Password

Register-ScheduledTask `
    -TaskName "MCP_HealthCheck" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "每 5 分鐘執行 MCP 5 層健康檢查" `
    -Force
```

---

## 工作 2：MCP_HourlyRestart（每小時）

### Task Scheduler GUI 步驟

1. **一般** 分頁：
   - 名稱：`MCP_HourlyRestart`
   - 描述：`每小時預防性重啟 MCP 服務`
   - 選取「不論使用者是否登入都要執行」
   - 勾選「以最高權限執行」
2. **觸發程序** 分頁 → 新增：
   - 開始工作：**依排程**
   - 設定：**每天**
   - 重複工作每：`1 小時`，持續時間：`無限期`
3. **動作** 分頁 → 新增：
   - 動作：**啟動程式**
   - 程式：`powershell.exe`
   - 引數：
     ```
     -NoProfile -ExecutionPolicy Bypass -File "V:\projects\mcp-handcraft\scripts\restart-mcp.ps1"
     ```
   - 起始位置：`V:\projects\mcp-handcraft`
4. **設定** 分頁：
   - 勾選「如果工作失敗，依下列頻率重新啟動」：每 `5 分鐘`，最多 `2` 次
   - 「如果要求的工作已在執行中」→ **不要啟動新執行個體**

### PowerShell 一鍵建立

```powershell
$repoRoot  = "V:\projects\mcp-handcraft"
$script    = Join-Path $repoRoot "scripts\restart-mcp.ps1"
$action    = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`"" `
    -WorkingDirectory $repoRoot

$trigger   = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Hours 1) -Once -At (Get-Date)
$settings  = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Password

Register-ScheduledTask `
    -TaskName "MCP_HourlyRestart" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "每小時預防性重啟 MCP 服務" `
    -Force
```

---

## 工作 3：MCP_DailyReport（每日 08:00）

### 說明

每日報告讀取 `healthcheck-summary.json` 歷史記錄（或 `healthcheck.log`），產生：
- 前 24 小時 pass/fail/skip 統計
- 最長連續失敗次數
- 報告寫入 `G:\AI_WORK_512\run\mcp-handcraft\daily-report-YYYYMMDD.txt`

### Task Scheduler GUI 步驟

1. **一般** 分頁：
   - 名稱：`MCP_DailyReport`
   - 描述：`每日 08:00 產生 MCP 健康摘要報告`
2. **觸發程序** 分頁 → 新增：
   - 開始工作：**依排程**
   - 設定：**每天**
   - 開始時間：`08:00:00`
3. **動作** 分頁 → 新增：
   - 程式：`powershell.exe`
   - 引數：
     ```
     -NoProfile -ExecutionPolicy Bypass -Command "& { $logFile='G:\AI_WORK_512\run\mcp-handcraft\healthcheck.log'; $report='G:\AI_WORK_512\run\mcp-handcraft\daily-report-' + (Get-Date -Format yyyyMMdd) + '.txt'; $since=(Get-Date).AddHours(-24); $lines=Get-Content -LiteralPath $logFile -ErrorAction SilentlyContinue | Where-Object { $_ -match '\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]' -and ([datetime]$Matches[1]) -ge $since }; $pass=($lines | Select-String 'status=OK').Count; $fail=($lines | Select-String 'status=FAIL|status=ALERT').Count; $maxConsec=($lines | ForEach-Object { if ($_ -match 'consecutive=(\d+)') { [int]$Matches[1] } else { 0 } } | Measure-Object -Maximum).Maximum; \"MCP Daily Report $(Get-Date -Format yyyy-MM-dd)`nPass: $pass  Fail: $fail  MaxConsecutiveFail: $maxConsec\" | Set-Content -LiteralPath $report -Encoding UTF8 }"
     ```

### PowerShell 一鍵建立

```powershell
$runtimeRoot = "G:\AI_WORK_512\run\mcp-handcraft"
$scriptBlock = @'
$logFile   = "G:\AI_WORK_512\run\mcp-handcraft\healthcheck.log"
$reportFile = "G:\AI_WORK_512\run\mcp-handcraft\daily-report-" + (Get-Date -Format "yyyyMMdd") + ".txt"
$since     = (Get-Date).AddHours(-24)
$lines     = Get-Content -LiteralPath $logFile -ErrorAction SilentlyContinue |
    Where-Object {
        $_ -match '\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]' -and
        ([datetime]$Matches[1]) -ge $since
    }
$pass      = ($lines | Select-String "status=OK").Count
$fail      = ($lines | Select-String "status=FAIL|status=ALERT").Count
$maxConsec = ($lines |
    ForEach-Object { if ($_ -match "consecutive=(\d+)") { [int]$Matches[1] } else { 0 } } |
    Measure-Object -Maximum).Maximum
$body = "MCP Daily Report $(Get-Date -Format 'yyyy-MM-dd')`nPass: $pass  Fail: $fail  MaxConsecutiveFail: $maxConsec"
$body | Set-Content -LiteralPath $reportFile -Encoding UTF8
Write-Host $body
'@

# 將 scriptBlock 儲存為暫存腳本（可選）或內嵌至 Argument
$action    = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument ("-NoProfile -ExecutionPolicy Bypass -Command `"& {{ {0} }}`"" -f ($scriptBlock -replace '"', '\"'))

$trigger   = New-ScheduledTaskTrigger -Daily -At "08:00"
$settings  = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -RunLevel Highest -LogonType Password

Register-ScheduledTask `
    -TaskName "MCP_DailyReport" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "每日 08:00 產生 MCP 健康摘要報告" `
    -Force
```

---

## 驗證所有工作

```powershell
# 列出三個工作狀態
Get-ScheduledTask -TaskName "MCP_HealthCheck", "MCP_HourlyRestart", "MCP_DailyReport" |
    Select-Object TaskName, State, LastRunTime, LastTaskResult

# 手動觸發測試（不等待完成）
Start-ScheduledTask -TaskName "MCP_HealthCheck"
Start-Sleep -Seconds 5
Get-ScheduledTaskInfo -TaskName "MCP_HealthCheck" | Select-Object LastRunTime, LastTaskResult
```

---

## 移除工作（如需重建）

```powershell
"MCP_HealthCheck", "MCP_HourlyRestart", "MCP_DailyReport" |
    ForEach-Object { Unregister-ScheduledTask -TaskName $_ -Confirm:$false -ErrorAction SilentlyContinue }
```

---

## 常見問題

| 問題 | 排查方向 |
|------|---------|
| 工作執行後 LastTaskResult = 0x1 | 查看 `G:\AI_WORK_512\run\mcp-handcraft\healthcheck.log` |
| 工作不觸發 | 確認「不論使用者是否登入都要執行」已選，並已輸入密碼 |
| PowerShell 找不到腳本 | 確認 repo 路徑與引數中的路徑一致 |
| 連續失敗不清零 | 刪除 `G:\AI_WORK_512\run\mcp-handcraft\healthcheck-state.json` |
