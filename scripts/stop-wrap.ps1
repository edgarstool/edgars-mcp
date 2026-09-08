<#
.SYNOPSIS
  停止 edgars-mcp HTTP（stdio wrap 子程序會跟著 Python 一起結束）。
  Stop edgars-mcp HTTP. Stdio wrap children die with the Python process.

.DESCRIPTION
  預設不殺 cloudflared、不關 1Password Connect。
  需要時才加 -StopCloudflared / -StopConnect。

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\stop-wrap.ps1
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [int]$Port = 8765,
    [string]$ConnectDir = "V:\projects\1password-connet",
    [switch]$StopCloudflared,
    [switch]$StopConnect,
    [switch]$Force,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

$stopMcp = Join-Path $PSScriptRoot "stop-mcp.ps1"
$stopArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $stopMcp,
    "-Port", "$Port"
)
if ($StopCloudflared) { $stopArgs += "-StopCloudflared" }
if ($Force) { $stopArgs += "-Force" }

Write-Host "[stop-wrap] stopping HTTP on :$Port"
& powershell.exe @stopArgs
$httpExit = $LASTEXITCODE

$connectResult = $null
if ($StopConnect) {
    $compose = $null
    foreach ($name in @("docker-compose.yaml", "docker-compose.yml")) {
        $candidate = Join-Path $ConnectDir $name
        if (Test-Path -LiteralPath $candidate) {
            $compose = $candidate
            break
        }
    }
    if (-not $compose) {
        throw "找不到 Connect compose：$ConnectDir"
    }
    Write-Host "[stop-wrap] docker compose down ($ConnectDir)"
    Push-Location $ConnectDir
    try {
        docker compose -f (Split-Path -Leaf $compose) down
        $connectResult = [ordered]@{
            ok     = ($LASTEXITCODE -eq 0)
            action = "compose_down"
            exit   = $LASTEXITCODE
        }
    } finally {
        Pop-Location
    }
}

$output = [ordered]@{
    ok             = ($httpExit -eq 0)
    action         = "stop-wrap"
    http_exit      = $httpExit
    stop_connect   = [bool]$StopConnect
    connect        = $connectResult
    stop_cloudflared = [bool]$StopCloudflared
    checked_at     = (Get-Date).ToString("o")
}

$output | ConvertTo-Json -Depth 6
if ($httpExit -ne 0) { exit $httpExit }
if ($connectResult -and -not $connectResult.ok) { exit 1 }
exit 0
