$ErrorActionPreference = 'Stop'
$SourceDir = if ($env:EDGARS_MCP_SOURCE_DIR) { $env:EDGARS_MCP_SOURCE_DIR } else { Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$ConfigDir = if ($env:EDGARS_MCP_CONFIG_DIR) { $env:EDGARS_MCP_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.config\edgars-mcp' }
$OpEnv = Join-Path $ConfigDir 'edgars-mcp.op.env'
$Python = Join-Path $SourceDir '.venv\Scripts\python.exe'

if (-not (Get-Command op -ErrorAction SilentlyContinue)) { throw '1Password CLI (op) is required.' }
if (-not (Test-Path $OpEnv)) { throw "Missing 1Password reference file: $OpEnv" }
Set-Location $SourceDir
& op run --env-file $OpEnv -- $Python -m edgars_mcp.http_server

