# 排程用健康檢查（只檢查、絕不重啟）
# 由 Windows 工作排程器 MCP-HealthCheck 每 5 分鐘呼叫
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$LogsDir    = Join-Path $RepoRoot 'logs'
$LogPath    = Join-Path $LogsDir ("patrol-healthcheck-{0:yyyyMMdd}.log" -f (Get-Date))
$CheckScript = Join-Path $PSScriptRoot 'check-mcp-health.ps1'
$DotLog     = Join-Path $PSScriptRoot 'patrol-write-log.ps1'

function Write-PatrolLog([string]$Message, [string]$Level = 'INFO') {
    & $DotLog -LogPath $LogPath -Message $Message -Level $Level
}

Write-PatrolLog '=== patrol-healthcheck 開始 ==='

if (-not (Test-Path -LiteralPath $CheckScript)) {
    Write-PatrolLog "找不到 $CheckScript" 'ERROR'
    exit 2
}

try {
    $output = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $CheckScript 2>&1
    $exit   = $LASTEXITCODE
    foreach ($line in ($output | Out-String).Trim().Split("`n")) {
        if ($line.Trim()) { Write-PatrolLog $line.Trim() }
    }
    if ($exit -eq 0) {
        Write-PatrolLog '健康檢查 PASS' 'OK'
    } else {
        Write-PatrolLog "健康檢查 FAIL（exit=$exit）— 等待 AutoRecover 處理，本腳本不重啟" 'WARN'
    }
    exit $exit
} catch {
    Write-PatrolLog $_.Exception.Message 'ERROR'
    exit 3
}
