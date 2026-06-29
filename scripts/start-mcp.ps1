<#
.SYNOPSIS
  啟動 handcraft MCP HTTP server，並在 Windows 背景執行（daemonize）。
  Start handcraft MCP HTTP server and detach to a background process on Windows.

.DESCRIPTION
  - 若本機 health 已正常，則不重複啟動（idempotent）。
  - 預設會一併確認/啟動 cloudflared tunnel；可用 -SkipCloudflared 略過。
  - PID 寫入 G:\AI_WORK_512\run\mcp-handcraft\handcraft-http.pid

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-mcp.ps1 -SkipCloudflared -LocalOnly
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [int]$Port = 8765,
    [int]$WaitSeconds = 30,
    [switch]$SkipCloudflared,
    [switch]$LocalOnly,
    [switch]$Force,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

$modulePath = Join-Path $PSScriptRoot "Handcraft-McpCommon.psm1"
Import-Module $modulePath -Force

$config = Get-HandcraftConfig -Port $Port -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl
$config | Add-Member -NotePropertyName WaitSeconds -NotePropertyValue $WaitSeconds -Force

Write-Host "[start-mcp] repo=$($config.RepoRoot)"
Write-Host "[start-mcp] health=$($config.LocalHealthUrl)"

$httpResult = Start-HandcraftHttpServer -Config $config -Force:$Force
if ($httpResult.already_running) {
    Write-Host "[start-mcp] HTTP server already healthy (pid=$($httpResult.pid))."
} else {
    Write-Host "[start-mcp] HTTP server started (pid=$($httpResult.pid))."
}

if (-not $SkipCloudflared -and -not $LocalOnly) {
    $tunnelResult = Start-HandcraftCloudflared -Config $config
    if ($tunnelResult.already_running) {
        Write-Host "[start-mcp] cloudflared already running (pid=$($tunnelResult.pid))."
    } else {
        Write-Host "[start-mcp] cloudflared started (pid=$($tunnelResult.pid))."
    }
}

$result = [ordered]@{
    ok = $true
    action = "start"
    http = $httpResult
    cloudflared = if ($SkipCloudflared -or $LocalOnly) { $null } else { $tunnelResult }
    pid_file = $config.HttpPidFile
    checked_at = (Get-Date).ToString("o")
}

$result | ConvertTo-Json -Depth 6
exit 0
