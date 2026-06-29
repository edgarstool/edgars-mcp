<#
.SYNOPSIS
  停止 handcraft MCP HTTP server（與可選 cloudflared）。
  Stop handcraft MCP HTTP server (and optional cloudflared).

.DESCRIPTION
  優先使用 PID file（G:\AI_WORK_512\run\mcp-handcraft\），
  若缺少則改以 :8765 監聽程序為目標。

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-mcp.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-mcp.ps1 -StopCloudflared -Force
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int]$Port = 8765,
    [switch]$StopCloudflared,
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

$config = Get-HandcraftConfig -Port $Port
$results = @()

if ($PSCmdlet.ShouldProcess("handcraft-http", "stop")) {
    $pidResult = Stop-HandcraftByPidFile -PidFile $config.HttpPidFile -Force:$Force
    if (-not $pidResult.stopped) {
        $ownerPid = Get-PortOwnerPid -Port $config.Port
        if ($ownerPid) {
            $stopArgs = @{ Id = $ownerPid }
            if ($Force) { $stopArgs.Force = $true }
            Stop-Process @stopArgs -ErrorAction Stop
            Remove-Item -LiteralPath $config.HttpPidFile -Force -ErrorAction SilentlyContinue
            $pidResult = [pscustomobject]@{ stopped = $true; pid = $ownerPid; reason = "port_owner" }
        }
    }
    $results += [ordered]@{ target = "handcraft-http"; result = $pidResult }
}

if ($StopCloudflared -and $PSCmdlet.ShouldProcess("cloudflared", "stop")) {
    $tunnelResult = Stop-HandcraftByPidFile -PidFile $config.CloudflaredPidFile -Force:$Force
    if (-not $tunnelResult.stopped) {
        $processes = @(Get-Process cloudflared -ErrorAction SilentlyContinue)
        foreach ($proc in $processes) {
            $stopArgs = @{ Id = $proc.Id }
            if ($Force) { $stopArgs.Force = $true }
            Stop-Process @stopArgs -ErrorAction SilentlyContinue
        }
        Remove-Item -LiteralPath $config.CloudflaredPidFile -Force -ErrorAction SilentlyContinue
        $tunnelResult = [pscustomobject]@{ stopped = ($processes.Count -gt 0); count = $processes.Count; reason = "process_scan" }
    }
    $results += [ordered]@{ target = "cloudflared"; result = $tunnelResult }
}

$output = [ordered]@{
    ok = $true
    action = "stop"
    results = $results
    checked_at = (Get-Date).ToString("o")
}

$output | ConvertTo-Json -Depth 6
exit 0
