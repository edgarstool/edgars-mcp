$ErrorActionPreference = 'Stop'
$SourceDir = if ($env:EDGARS_MCP_SOURCE_DIR) { $env:EDGARS_MCP_SOURCE_DIR } else { Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }
$ConfigDir = if ($env:EDGARS_MCP_CONFIG_DIR) { $env:EDGARS_MCP_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.config\edgars-mcp' }
$RuntimeDir = if ($env:EDGARS_MCP_RUNTIME_DIR) { $env:EDGARS_MCP_RUNTIME_DIR } else { Join-Path $env:LOCALAPPDATA 'edgars-mcp' }

New-Item -ItemType Directory -Force -Path $ConfigDir, $RuntimeDir | Out-Null
python -m venv (Join-Path $SourceDir '.venv')
& (Join-Path $SourceDir '.venv\Scripts\python.exe') -m pip install -e "$SourceDir[all]"
Copy-Item (Join-Path $SourceDir 'config\edgars-mcp.op.env.example') (Join-Path $ConfigDir 'edgars-mcp.op.env') -ErrorAction SilentlyContinue
Write-Host 'Installed. Edit the 1Password references, then run deploy\windows\start.ps1.'

