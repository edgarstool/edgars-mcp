<#
.SYNOPSIS
  跑 wrap 單元測試與 live verify（native surfaces）。
  Run wrap unit tests plus live native-surface verification.

.DESCRIPTION
  預設不拉起 Playwright / Windows-MCP / Desktop Commander stdio（verify script 預設關）。
  加 -IncludeStdio 才會測這三個。

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-wrap.ps1
#>
[CmdletBinding()]
param(
    [switch]$IncludeStdio,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    $pyExe = $py.Source
    $pyPrefix = @("-3")
} else {
    $python = Get-Command python -ErrorAction Stop
    $pyExe = $python.Source
    $pyPrefix = @()
}

Write-Host "[test-wrap] unittest test_mcp_upstreams.py"
& $pyExe @pyPrefix -m unittest test_mcp_upstreams.py
$unitExit = $LASTEXITCODE

$verifyEnv = @{}
if ($IncludeStdio) {
    $verifyEnv = @{
        MCP_WRAP_PLAYWRIGHT         = "1"
        MCP_WRAP_WINDOWS            = "1"
        MCP_WRAP_DESKTOP_COMMANDER  = "1"
    }
    Write-Host "[test-wrap] verify-wrapped-tools.py (含 stdio MCP)"
} else {
    Write-Host "[test-wrap] verify-wrapped-tools.py (native only；stdio MCP 略過)"
}

foreach ($key in $verifyEnv.Keys) {
    Set-Item -Path "Env:$key" -Value $verifyEnv[$key]
}

& $pyExe @pyPrefix (Join-Path $PSScriptRoot "verify-wrapped-tools.py")
$verifyExit = $LASTEXITCODE

$result = [ordered]@{
    ok          = ($unitExit -eq 0 -and $verifyExit -eq 0)
    action      = "test-wrap"
    unittest    = $unitExit
    verify      = $verifyExit
    include_stdio = [bool]$IncludeStdio
    checked_at  = (Get-Date).ToString("o")
}

Write-Host ""
$result | ConvertTo-Json -Depth 4
if ($result.ok) { exit 0 } else { exit 1 }
