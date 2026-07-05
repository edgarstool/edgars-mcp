<#
.SYNOPSIS
  安裝 / 更新 Edgars MCP 自動巡邏的 Windows 工作排程器任務（可重複執行）。

.DESCRIPTION
  註冊四個排程任務：
    - MCP-HealthCheck     每 5 分鐘   只檢查、不重啟
    - MCP-AutoRecover     每 15 分鐘  連續失敗 3 次才重啟 MCP；orchestrator 掛了會啟動
    - MCP-Maintain-Daily  每天 04:00  完整維護
    - MCP-LoginStart      使用者登入  啟動 MCP + orchestrator

.PARAMETER Uninstall
  移除上述排程任務（不刪除腳本）。

.PARAMETER WhatIf
  只顯示將要做什麼，不實際註冊。

.EXAMPLE
  cd V:\projects\mcp-handcraft
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-patrol-scheduler.ps1

  若 UAC 跳出，請按「是」— 註冊排程通常需要系統管理員權限。
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

# 無限期重複的近似值（Task Scheduler 不接受 TimeSpan::MaxValue）
$PatrolRepeatDuration = New-TimeSpan -Days 3650
$RepoRoot    = Split-Path -Parent $PSScriptRoot
$TaskFolder  = '\Edgars\'
$RunAsUser   = (whoami).Trim()
$PsExe       = (Get-Command powershell.exe).Source
$PsArgsBase  = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File'

function Get-TaskFullName([string]$ShortName) {
    return ($TaskFolder.TrimEnd('\') + '\' + $ShortName)
}

function New-PatrolTaskAction([string]$ScriptPath) {
    $arg = "$PsArgsBase `"$ScriptPath`""
    return New-ScheduledTaskAction -Execute $PsExe -Argument $arg
}

function New-PatrolTaskSettings {
    $s = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
        -MultipleInstances IgnoreNew
    return $s
}

function Register-PatrolTask {
    param(
        [string]$ShortName,
        [string]$Description,
        [string]$ScriptPath,
        [object]$Trigger,
        [string]$UserId = $RunAsUser
    )

    $fullName = Get-TaskFullName $ShortName
    $action   = New-PatrolTaskAction -ScriptPath $ScriptPath
    $settings = New-PatrolTaskSettings
    $principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

    if ($PSCmdlet.ShouldProcess($fullName, 'Register-ScheduledTask')) {
        $existing = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $ShortName -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Host "  更新排程：$fullName" -ForegroundColor Yellow
            Unregister-ScheduledTask -TaskPath $TaskFolder -TaskName $ShortName -Confirm:$false
        } else {
            Write-Host "  新增排程：$fullName" -ForegroundColor Green
        }

        Register-ScheduledTask `
            -TaskPath $TaskFolder `
            -TaskName $ShortName `
            -Action $action `
            -Trigger $Trigger `
            -Settings $settings `
            -Principal $principal `
            -Description $Description | Out-Null
    } else {
        Write-Host "  [WhatIf] 會註冊：$fullName → $ScriptPath" -ForegroundColor DarkGray
    }
}

function Unregister-PatrolTasks {
    $names = @('MCP-HealthCheck', 'MCP-AutoRecover', 'MCP-Maintain-Daily', 'MCP-LoginStart')
    foreach ($n in $names) {
        $full = Get-TaskFullName $n
        if ($PSCmdlet.ShouldProcess($full, 'Unregister-ScheduledTask')) {
            $t = Get-ScheduledTask -TaskPath $TaskFolder -TaskName $n -ErrorAction SilentlyContinue
            if ($t) {
                Unregister-ScheduledTask -TaskPath $TaskFolder -TaskName $n -Confirm:$false
                Write-Host "  已移除：$full" -ForegroundColor Yellow
            } else {
                Write-Host "  不存在（略過）：$full" -ForegroundColor DarkGray
            }
        }
    }
}

# --- 前置檢查 ---
Write-Host ''
Write-Host '  Edgars MCP 自動巡邏 — 排程安裝' -ForegroundColor Cyan
Write-Host "  repo: $RepoRoot" -ForegroundColor DarkGray
Write-Host ''

$requiredScripts = @(
    (Join-Path $PSScriptRoot 'patrol-healthcheck.ps1'),
    (Join-Path $PSScriptRoot 'patrol-auto-recover.ps1'),
    (Join-Path $PSScriptRoot 'patrol-maintain-daily.ps1'),
    (Join-Path $PSScriptRoot 'patrol-login-start.ps1'),
    (Join-Path $PSScriptRoot 'check-mcp-health.ps1'),
    (Join-Path $PSScriptRoot 'restart-mcp.ps1'),
    (Join-Path $PSScriptRoot 'maintain-mcp.ps1')
)

$missing = $requiredScripts | Where-Object { -not (Test-Path -LiteralPath $_) }
if ($missing) {
    Write-Host '  下列腳本不存在，請先確認 mcp-handcraft repo 完整：' -ForegroundColor Red
    $missing | ForEach-Object { Write-Host "    $_" -ForegroundColor Red }
    Write-Host ''
    Write-Host '  若你剛 git pull，請再執行一次。缺少的可能是舊版尚未 commit 的 ops 腳本。' -ForegroundColor Yellow
    exit 1
}

$logsDir = Join-Path $RepoRoot 'logs'
if (-not (Test-Path -LiteralPath $logsDir)) {
    if ($PSCmdlet.ShouldProcess($logsDir, 'New-Item Directory')) {
        New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
    }
}

if ($Uninstall) {
    Write-Host '移除巡邏排程…' -ForegroundColor Cyan
    Unregister-PatrolTasks
    Write-Host ''
    Write-Host '完成。腳本檔仍保留在 scripts\ 資料夾。' -ForegroundColor Green
    exit 0
}

# --- 建立觸發條件 ---
# 每 5 分鐘：從現在起每 5 分鐘重複（無限期）
$triggerHealth = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 5) `
    -RepetitionDuration $PatrolRepeatDuration

# 每 15 分鐘：錯開 2 分鐘，避免與 healthcheck 同秒碰撞
$recoverStart = (Get-Date).Date.AddMinutes(2)
$triggerRecover = New-ScheduledTaskTrigger -Once -At $recoverStart `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration $PatrolRepeatDuration

# 每天凌晨 4:00
$triggerDaily = New-ScheduledTaskTrigger -Daily -At '04:00'

# 使用者登入時
$triggerLogin = New-ScheduledTaskTrigger -AtLogOn -User $RunAsUser

Write-Host '註冊巡邏排程…' -ForegroundColor Cyan

Register-PatrolTask -ShortName 'MCP-HealthCheck' `
    -Description 'Edgars MCP：每 5 分鐘健康檢查（只檢查、不重啟）' `
    -ScriptPath (Join-Path $PSScriptRoot 'patrol-healthcheck.ps1') `
    -Trigger $triggerHealth

Register-PatrolTask -ShortName 'MCP-AutoRecover' `
    -Description 'Edgars MCP：每 15 分鐘自動修復（連續失敗 3 次重啟 MCP；orchestrator 掛了會啟動）' `
    -ScriptPath (Join-Path $PSScriptRoot 'patrol-auto-recover.ps1') `
    -Trigger $triggerRecover

Register-PatrolTask -ShortName 'MCP-Maintain-Daily' `
    -Description 'Edgars MCP：每天凌晨 4 點完整維護' `
    -ScriptPath (Join-Path $PSScriptRoot 'patrol-maintain-daily.ps1') `
    -Trigger $triggerDaily

Register-PatrolTask -ShortName 'MCP-LoginStart' `
    -Description 'Edgars MCP：使用者登入時啟動 handcraft HTTP 與 linear-orchestrator' `
    -ScriptPath (Join-Path $PSScriptRoot 'patrol-login-start.ps1') `
    -Trigger $triggerLogin

Write-Host ''
Write-Host '================================' -ForegroundColor Cyan
Write-Host '  排程已就緒（或 WhatIf 預覽完成）' -ForegroundColor Green
Write-Host ''
Write-Host '  任務名稱（工作排程器裡找 \Edgars\）：' -ForegroundColor White
Write-Host '    MCP-HealthCheck      每 5 分鐘' -ForegroundColor DarkGray
Write-Host '    MCP-AutoRecover      每 15 分鐘' -ForegroundColor DarkGray
Write-Host '    MCP-Maintain-Daily   每天 04:00' -ForegroundColor DarkGray
Write-Host '    MCP-LoginStart       登入時' -ForegroundColor DarkGray
Write-Host ''
Write-Host "  日誌資料夾：$logsDir" -ForegroundColor DarkGray
Write-Host '  健康摘要：G:\AI_WORK_512\run\mcp-handcraft\healthcheck-summary.json' -ForegroundColor DarkGray
Write-Host ''
Write-Host '  驗證：開啟「工作排程器」→ 工作排程器程式庫 → Edgars' -ForegroundColor Yellow
Write-Host '  或：Get-ScheduledTask -TaskPath \Edgars\' -ForegroundColor Yellow
Write-Host '================================' -ForegroundColor Cyan
Write-Host ''
