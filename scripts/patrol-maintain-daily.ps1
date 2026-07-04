# 排程用每日維護（可選重啟不健康服務）
# 由 Windows 工作排程器 MCP-Maintain-Daily 每天凌晨 4:00 呼叫
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot = Split-Path -Parent $PSScriptRoot
$LogsDir  = Join-Path $RepoRoot 'logs'
$LogPath  = Join-Path $LogsDir ("patrol-maintain-{0:yyyyMMdd}.log" -f (Get-Date))
$DotLog   = Join-Path $PSScriptRoot 'patrol-write-log.ps1'
$Maintain = Join-Path $PSScriptRoot 'maintain-mcp.ps1'

function Write-PatrolLog([string]$Message, [string]$Level = 'INFO') {
    & $DotLog -LogPath $LogPath -Message $Message -Level $Level
}

Write-PatrolLog '=== patrol-maintain-daily 開始 ==='

if (-not (Test-Path -LiteralPath $Maintain)) {
    Write-PatrolLog "找不到 $Maintain" 'ERROR'
    exit 2
}

try {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $Maintain -RestartIfUnhealthy 2>&1 | ForEach-Object {
        Write-PatrolLog $_.ToString()
    }
    Write-PatrolLog "maintain-mcp 完成（exit=$LASTEXITCODE）" $(if ($LASTEXITCODE -eq 0) { 'OK' } else { 'WARN' })
    exit $LASTEXITCODE
} catch {
    Write-PatrolLog $_.Exception.Message 'ERROR'
    exit 3
}
