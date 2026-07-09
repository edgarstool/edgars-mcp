<#
.SYNOPSIS
  檢驗 handcraft MCP 本機與外網連線狀態。
  Validate local and external handcraft MCP connectivity.

.DESCRIPTION
  檢查項目：
  - 本機：port、/health、可選 MCP tools/list handshake
  - 基礎設施：doppler、cloudflared 程序
  - 外網：public /mcp GET + OAuth discovery PRM（預設 https://mcp.edgars.tools/mcp）

  Exit code: 0 = 全部通過；1 = 有失敗項目

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp.ps1 -SkipPublic -SkipMcpHandshake
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [int]$Port = 8765,
    [int]$TimeoutSec = 10,
    [switch]$SkipPublic,
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

$checks = @()
$localChecks = @()
$externalChecks = @()
$infraChecks = @()

$ownerPid = Get-PortOwnerPid -Port $config.Port
$pidFromFile = Read-HandcraftPidFile -Path $config.HttpPidFile
$pidFileOk = $true
$pidFileDetail = [ordered]@{
    present = [bool]$pidFromFile
    pid     = $pidFromFile
    path    = $config.HttpPidFile
}
if ($pidFromFile) {
    $pidFileOk = (Test-ProcessAlive -ProcessId $pidFromFile) -or ($ownerPid -eq $pidFromFile)
    $pidFileDetail.valid = $pidFileOk
} else {
    $pidFileOk = $true
    $pidFileDetail.valid = $null
    $pidFileDetail.note = "optional until start-mcp.ps1 has been run"
}

$localChecks += [ordered]@{
    name = "port_listening"
    ok   = Test-PortListening -Port $config.Port
    port = $config.Port
    pid  = $ownerPid
}
$localChecks += Invoke-HandcraftHttpProbe -Name "health" -Uri $config.LocalHealthUrl -TimeoutSec $TimeoutSec

if (-not $SkipMcpHandshake) {
    $localChecks += Invoke-HandcraftLocalMcpHandshake -McpUrl $config.LocalMcpUrl -TimeoutSec $TimeoutSec
}

$infraChecks += [ordered]@{
    name = "doppler_command"
    ok   = Test-CommandAvailable -Name "doppler"
}
$infraChecks += [ordered]@{
    name = "cloudflared_command"
    ok   = Test-CommandAvailable -Name "cloudflared"
}
$infraChecks += [ordered]@{
    name = "cloudflared_process"
    ok   = [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
}
$infraChecks += [ordered]@{
    name = "pid_file"
    ok   = $pidFileOk
    pid  = $pidFromFile
    path = $config.HttpPidFile
    present = $pidFileDetail.present
    note = $pidFileDetail.note
}

if (-not $SkipPublic) {
    $publicBaseUrl = ($config.PublicMcpUrl -replace "/mcp$", "")
    $publicProbe = Invoke-HandcraftHttpProbe -Name "public_mcp_get" -Uri $config.PublicMcpUrl -TimeoutSec $TimeoutSec
    if ($publicProbe.ok -and $publicProbe.detail -eq "cloudflare_access_login") {
        $publicProbe.note = "reachable_access_protected"
    }
    if (-not $publicProbe.ok -and $publicProbe.status -in @(302, 401, 405, 406)) {
        $publicProbe.ok = $true
        $publicProbe.note = "reachable_auth_required"
    }
    $externalChecks += $publicProbe

    $publicPrmProbe = Invoke-HandcraftHttpProbe -Name "public_prm" -Uri "$publicBaseUrl/.well-known/oauth-protected-resource" -TimeoutSec $TimeoutSec
    if (-not $publicPrmProbe.ok -and $publicPrmProbe.status -eq 200) {
        $publicPrmProbe.ok = $true
        $publicPrmProbe.note = "oauth_discovery_ready"
    }
    $externalChecks += $publicPrmProbe
}

$checks = $localChecks + $infraChecks + $externalChecks

$localOk = -not [bool]($localChecks | Where-Object { -not $_.ok })
$externalOk = if ($SkipPublic) { $null } else { -not [bool]($externalChecks | Where-Object { -not $_.ok }) }
$infraOk = -not [bool]($infraChecks | Where-Object { -not $_.ok })
$allOk = $localOk -and $infraOk -and (($null -eq $externalOk) -or $externalOk)

$summary = [ordered]@{
    local    = if ($localOk) { "OK" } else { "FAIL" }
    external = if ($SkipPublic) { "SKIPPED" } elseif ($externalOk) { "OK" } else { "FAIL" }
    infra    = if ($infraOk) { "OK" } else { "FAIL" }
}

$result = [ordered]@{
    ok               = $allOk
    summary          = $summary
    local_base_url   = $config.LocalBaseUrl
    public_mcp_url   = if ($SkipPublic) { $null } else { $config.PublicMcpUrl }
    checked_at       = (Get-Date).ToString("o")
    checks           = $checks
}

Write-Host ""
Write-Host "=== handcraft MCP check ==="
Write-Host ("LOCAL    : {0}" -f $summary.local)
Write-Host ("EXTERNAL : {0}" -f $summary.external)
Write-Host ("INFRA    : {0}" -f $summary.infra)
Write-Host ""

$result | ConvertTo-Json -Depth 8
if (-not $allOk) {
    exit 1
}
exit 0
