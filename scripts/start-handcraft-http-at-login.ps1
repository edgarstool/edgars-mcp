$ErrorActionPreference = "Stop"

# Windows login / scheduled-task entry:
# Task edgars-mcp-http -> Start_Handcraft_MCP_HTTP.vbs -> this script.
# Native path only: no Docker, no 1Password Connect / op run, no Doppler.

$repo = "V:\projects\edgars-mcp"
$preferredPython = "C:\Users\EdgarsTool\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$server = Join-Path $repo "server_http.py"
$logDir = Join-Path $repo "logs"
$outLog = Join-Path $logDir "handcraft-http.out.log"
$errLog = Join-Path $logDir "handcraft-http.err.log"
$bootstrapLog = Join-Path $logDir "handcraft-http-login.log"

function Write-BootstrapLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $bootstrapLog -Value "[$timestamp] $Message" -ErrorAction SilentlyContinue
}

function Get-ScopedEnv {
    param([string]$Name)
    foreach ($scope in @("Process", "User", "Machine")) {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value.Trim()
        }
    }
    return $null
}

function Set-ProcessEnvFromScopes {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $value = Get-ScopedEnv -Name $name
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            Set-Item -Path "Env:$name" -Value $value
        }
    }
}

function Resolve-PythonExe {
    if (Test-Path -LiteralPath $preferredPython) {
        return $preferredPython
    }
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { return $py.Source }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) { return $python.Source }
    throw "Python executable not found."
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Rebuild persistent Windows PATH for scheduled-task / login context.
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

# Bearer still required for local tools / fallback; Descope is primary public auth.
$token = Get-ScopedEnv -Name "MCP_API_TOKEN"
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "MCP_API_TOKEN is missing (Machine or User scope)."
}
$env:MCP_API_TOKEN = $token

# Descope JWT auth (public project / resource-server ids; no Docker / 1Password).
$descopeDefaults = @{
    MCP_DESCOPE_ENABLED            = "true"
    MCP_DESCOPE_PROJECT_ID         = "P3IHk9JHELKS5KT5EWawFro5aPhY"
    MCP_DESCOPE_RESOURCE_SERVER_ID = "RS3IPp7u1MjAlO6wHaafMEw6bgu4C"
    MCP_DESCOPE_AUDIENCE           = "https://mcp.edgars.tools/mcp"
    MCP_AUTH_SERVER                = "https://auth.edgars.tools"
    MCP_BASE_URL                   = "https://mcp.edgars.tools"
    MCP_BIND_HOST                  = "0.0.0.0"
}
foreach ($key in $descopeDefaults.Keys) {
    $existing = Get-ScopedEnv -Name $key
    if ([string]::IsNullOrWhiteSpace($existing)) {
        Set-Item -Path "Env:$key" -Value $descopeDefaults[$key]
    } else {
        Set-Item -Path "Env:$key" -Value $existing
    }
}

# Propagate common non-secret + already-persisted User/Machine secrets into this process.
Set-ProcessEnvFromScopes -Names @(
    "DESCOPE_PROJECT_ID",
    "DESCOPE_MANAGEMENT_KEY",
    "DESCOPE_MCP_WELL_KNOWN_URL",
    "OPENAI_API_KEY",
    "CURSOR_API_KEY",
    "HONCHO_API_KEY",
    "LINEAR_API_KEY",
    "PERPLEXITY_API_KEY",
    "WARP_API_KEY",
    "FACTORY_API_KEY",
    "TRACKTW_API_KEY",
    "EDGARS_HONCHO_MCP_FACADE_TOKEN"
)

# Full Windows-native wrapper set (1Password Connect explicitly off).
$env:MCP_WRAP_ALL = "0"
$env:MCP_WRAP_ALLOW_REMOTE = "1"
$env:MCP_WRAP_DESCOPE = "1"
$env:MCP_WRAP_CLOUDFLARED = "1"
$env:MCP_WRAP_OPENMONTAGE = "1"
$env:MCP_WRAP_HERMES = "1"
$env:MCP_WRAP_OPENCLAW = "1"
$env:MCP_WRAP_PLAYWRIGHT = "1"
$env:MCP_WRAP_WINDOWS = "1"
$env:MCP_WRAP_DESKTOP_COMMANDER = "1"
$env:MCP_WRAP_OP_CONNECT = "0"

function Test-Health {
    try {
        $response = Invoke-WebRequest `
            -Uri "http://127.0.0.1:8765/health" `
            -UseBasicParsing `
            -TimeoutSec 2
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

if (Test-Health) {
    Write-BootstrapLog "Already healthy; skip start."
    exit 0
}

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*V:\projects\edgars-mcp\server_http.py*" } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

Start-Sleep -Milliseconds 500

$python = Resolve-PythonExe
Write-BootstrapLog "Starting native HTTP via $python (Descope auth, no Docker/1Password)."

Start-Process `
    -FilePath $python `
    -ArgumentList @($server) `
    -WorkingDirectory $repo `
    -WindowStyle Hidden `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Health) {
        Write-BootstrapLog "Health OK after $($i + 1)s."
        exit 0
    }
}

Write-BootstrapLog "Failed to reach health=200. See $errLog"
throw "edgars-mcp HTTP backend failed to reach health=200."
