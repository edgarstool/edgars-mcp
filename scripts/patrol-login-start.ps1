# 登入時啟動：handcraft MCP HTTP + linear-orchestrator（若尚未運行）
# 由 Windows 工作排程器 MCP-LoginStart 在使用者登入時呼叫
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$LogsDir    = Join-Path $RepoRoot 'logs'
$LogPath    = Join-Path $LogsDir ("patrol-login-{0:yyyyMMdd}.log" -f (Get-Date))
$DotLog     = Join-Path $PSScriptRoot 'patrol-write-log.ps1'
$LoginMcp   = Join-Path $PSScriptRoot 'start-handcraft-http-at-login.ps1'
$Recover    = Join-Path $PSScriptRoot 'patrol-auto-recover.ps1'

function Write-PatrolLog([string]$Message, [string]$Level = 'INFO') {
    & $DotLog -LogPath $LogPath -Message $Message -Level $Level
}

Write-PatrolLog '=== patrol-login-start（登入自啟）開始 ==='

if (Test-Path -LiteralPath $LoginMcp) {
    Write-PatrolLog '執行 start-handcraft-http-at-login.ps1 …'
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $LoginMcp 2>&1 | ForEach-Object {
            Write-PatrolLog $_.ToString()
        }
        Write-PatrolLog "MCP 登入啟動腳本完成（exit=$LASTEXITCODE）"
    } catch {
        Write-PatrolLog "MCP 登入啟動失敗: $($_.Exception.Message)" 'ERROR'
    }
} else {
    Write-PatrolLog "找不到 $LoginMcp — 跳過 MCP 登入啟動" 'WARN'
}

# 只啟動 orchestrator（登入時不重啟 MCP）
if (Test-Path -LiteralPath $Recover) {
    Write-PatrolLog '檢查 linear-orchestrator …'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Recover -OrchestratorOnly 2>&1 | ForEach-Object {
        Write-PatrolLog $_.ToString()
    }
}

Write-PatrolLog '=== patrol-login-start 結束 ==='
