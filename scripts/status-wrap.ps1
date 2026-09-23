<# Show canonical edgars-mcp HTTP/cloudflared/tool status. #>
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
if ($Help) { Get-Help $PSCommandPath -Full; exit 0 }

Import-Module (Join-Path $PSScriptRoot "Handcraft-McpCommon.psm1") -Force
$config = Get-HandcraftConfig -Port $Port -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl
$ownerPid = Get-PortOwnerPid -Port $config.Port
$health = Invoke-HandcraftHttpProbe -Name "health" -Uri $config.LocalHealthUrl -TimeoutSec $TimeoutSec
$cfProcs = @(Get-Process cloudflared -ErrorAction SilentlyContinue)
$handshake = $null
if (-not $SkipMcpHandshake) {
    $handshake = Invoke-HandcraftLocalMcpHandshake -McpUrl $config.LocalMcpUrl -TimeoutSec $TimeoutSec
}

Write-Host ""
Write-Host "=== edgars-mcp canonical status ==="
Write-Host ("HTTP :{0} {1} pid={2}" -f $config.Port, $(if ($health.ok) { "OK" } else { "DOWN" }), $ownerPid)
Write-Host ("cloudflared {0} process(es)" -f $cfProcs.Count)
if ($handshake) {
    Write-Host ("MCP handshake {0}" -f $(if ($handshake.ok) { "OK tools=$($handshake.tool_count)" } else { "FAIL" }))
}

$result = [ordered]@{
    ok = [bool]($health.ok)
    action = "status-wrap"
    http = $health
    port = $config.Port
    pid = $ownerPid
    cloudflared = @{ count = $cfProcs.Count; pids = @($cfProcs | ForEach-Object { $_.Id }) }
    handshake = $handshake
    expected_tools = 253
    checked_at = (Get-Date).ToString("o")
}
$result | ConvertTo-Json -Depth 6
if ($health.ok) { exit 0 } else { exit 1 }
