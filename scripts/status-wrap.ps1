<#
.SYNOPSIS
  顯示 edgars-mcp HTTP、Connect、cloudflared、wrap 開關狀態。
  Show HTTP / Connect / cloudflared / wrap flag status.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\status-wrap.ps1
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [int]$Port = 8765,
    [int]$TimeoutSec = 10,
    [switch]$SkipMcpHandshake,
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

function Test-ConnectHealthDetail {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8877/health" -TimeoutSec 3
        return [ordered]@{
            ok     = ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
            status = [int]$response.StatusCode
            uri    = "http://127.0.0.1:8877/health"
        }
    } catch {
        return [ordered]@{
            ok     = $false
            status = $null
            uri    = "http://127.0.0.1:8877/health"
            error  = $_.Exception.Message
        }
    }
}

$ownerPid = Get-PortOwnerPid -Port $config.Port
$pidFromFile = Read-HandcraftPidFile -Path $config.HttpPidFile
$health = Invoke-HandcraftHttpProbe -Name "health" -Uri $config.LocalHealthUrl -TimeoutSec $TimeoutSec
$connect = Test-ConnectHealthDetail
$cfProcs = @(Get-Process cloudflared -ErrorAction SilentlyContinue)
$launcherPath = Join-Path $config.RuntimeRoot "handcraft-op-launch.cmd"
$launcherWrap = $false
$launcherText = $null
if (Test-Path -LiteralPath $launcherPath) {
    $launcherText = Get-Content -LiteralPath $launcherPath -Raw -ErrorAction SilentlyContinue
    $launcherWrap = [bool]($launcherText -match '(?m)^set MCP_WRAP_ALL=1\s*$')
}

$handshake = $null
if (-not $SkipMcpHandshake) {
    $handshake = Invoke-HandcraftLocalMcpHandshake -McpUrl $config.LocalMcpUrl -TimeoutSec $TimeoutSec
}

Write-Host ""
Write-Host "=== edgars-mcp 狀態 ==="
Write-Host ("HTTP :{0}     {1}  pid={2}" -f $config.Port, $(if ($health.ok) { "OK" } else { "DOWN" }), $ownerPid)
Write-Host ("PID file      {0}" -f $(if ($pidFromFile) { $pidFromFile } else { "(none)" }))
Write-Host ("Connect :8877  {0}" -f $(if ($connect.ok) { "OK" } else { "DOWN" }))
Write-Host ("cloudflared    {0} process(es)" -f $cfProcs.Count)
Write-Host ("launcher wrap  {0}" -f $(if ($launcherWrap) { "MCP_WRAP_ALL=1" } else { "off / missing" }))
if ($handshake) {
    $hs = if ($handshake.ok) { "OK tools=$($handshake.tool_count)" } else { "FAIL $($handshake.error)" }
    Write-Host ("MCP handshake  {0}" -f $hs)
    if ($handshake.ok -and $handshake.tool_count -and [int]$handshake.tool_count -le 90) {
        Write-Host "提示：tool 數看起來像 wrap 仍關著。請雙擊「啟動 edgars-mcp」重啟。"
    }
}
Write-Host ""

$result = [ordered]@{
    ok             = [bool]($health.ok)
    action         = "status-wrap"
    http           = $health
    port           = $config.Port
    pid            = $ownerPid
    pid_file       = $pidFromFile
    connect        = $connect
    cloudflared    = @{ count = $cfProcs.Count; pids = @($cfProcs | ForEach-Object { $_.Id }) }
    launcher_path  = $launcherPath
    launcher_wrap  = $launcherWrap
    handshake      = $handshake
    checked_at     = (Get-Date).ToString("o")
}

$result | ConvertTo-Json -Depth 6
if ($health.ok) { exit 0 } else { exit 1 }
