<#
.SYNOPSIS
  檢驗 handcraft MCP 本機與外網連線狀態。
  Validate local and external handcraft MCP connectivity.

.DESCRIPTION
  檢查項目：
  - 本機：port、/health、可選 MCP tools/list handshake
  - 基礎設施：doppler、cloudflared 程序
  - 外網：public /mcp GET（預設 https://mcp.edgars.tools/mcp）

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
    ok   = Test-HandcraftCloudflaredHealthy
    note = "expects Windows Cloudflared service or tunnel run edgar-local-01-tunnel; not deprecated config.yml"
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
    $publicProbe = Invoke-HandcraftHttpProbe -Name "public_mcp_get" -Uri $config.PublicMcpUrl -TimeoutSec $TimeoutSec
    $publicBody = $null
    try {
        $publicResponse = Invoke-WebRequest -UseBasicParsing -Uri $config.PublicMcpUrl -TimeoutSec $TimeoutSec `
            -Headers @{ "Cache-Control" = "no-cache" }
        $publicBody = [string]$publicResponse.Content
        if ($null -eq $publicProbe.status) {
            $publicProbe.status = [int]$publicResponse.StatusCode
        }
    } catch {
        if ($_.Exception.Response) {
            try {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $publicBody = [string]$reader.ReadToEnd()
                $reader.Close()
                $publicProbe.status = [int]$_.Exception.Response.StatusCode
            } catch {
                $publicBody = $null
            }
        }
    }

    if ($publicProbe.ok -and $publicBody -eq "Hello world") {
        $publicProbe.ok = $false
        $publicProbe.detail = "wrong_backend_hello_world"
        $publicProbe.note = "Cloudflare Worker route *.edgars.tools/* (script edgars) is intercepting tunnel traffic; remove or narrow that route in Dashboard"
    } elseif ($publicProbe.ok -and $publicBody -match '"server"\s*:|oauth-protected-resource|Unauthorized') {
        $publicProbe.note = "reachable_mcp_or_oauth"
    } elseif ($publicProbe.ok -and $publicProbe.detail -eq "cloudflare_access_login") {
        $publicProbe.note = "reachable_access_protected"
    } elseif (-not $publicProbe.ok -and $publicProbe.status -in @(302, 401, 403, 405)) {
        $publicProbe.ok = $true
        $publicProbe.note = "reachable_auth_required"
    }
    if ($publicBody) {
        $publicProbe.body_preview = if ($publicBody.Length -gt 120) { $publicBody.Substring(0, 120) + "..." } else { $publicBody }
    }
    $externalChecks += $publicProbe
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
