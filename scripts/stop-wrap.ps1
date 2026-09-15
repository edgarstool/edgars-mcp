<# Compatibility entry point for stopping the canonical edgars-mcp HTTP server. #>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [switch]$StopCloudflared,
    [switch]$Force,
    [switch]$Help
)
$ErrorActionPreference = 'Stop'
if ($Help) { Get-Help $PSCommandPath -Full; exit 0 }

$stop = Join-Path $PSScriptRoot 'stop-mcp.ps1'
$mcpArgs = @('-NoProfile','-ExecutionPolicy','Bypass','-File',$stop,'-Port',"$Port")
if ($StopCloudflared) { $mcpArgs += '-StopCloudflared' }
if ($Force) { $mcpArgs += '-Force' }
& powershell.exe @mcpArgs
exit $LASTEXITCODE
