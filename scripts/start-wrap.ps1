<#
Compatibility entry point. The canonical 269-tool profile now lives in start-mcp.ps1.
No retired secret-runner or container bootstrap path is used.
#>
[CmdletBinding()]
param(
    [switch]$NoForce,
    [switch]$StartCloudflared,
    [switch]$Help
)

$ErrorActionPreference = 'Stop'
if ($Help) { Get-Help $PSCommandPath -Full; exit 0 }

$start = Join-Path $PSScriptRoot 'start-mcp.ps1'
$mcpArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$start)
if (-not $NoForce) { $mcpArgs += '-Force' }
if (-not $StartCloudflared) { $mcpArgs += '-SkipCloudflared' }

& powershell.exe @mcpArgs
exit $LASTEXITCODE
