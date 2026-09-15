$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$startScript = Join-Path $repoRoot "scripts\start-mcp.ps1"
$bootstrapLog = Join-Path $repoRoot "mcp-http-startup.log"

function Write-BootstrapLog {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $bootstrapLog -Value "[$timestamp] $Message"
}

function Import-WindowsEnvironment {
    foreach ($target in @('Machine','User')) {
        $vars = [Environment]::GetEnvironmentVariables($target)
        foreach ($name in $vars.Keys) {
            if ([string]$name -eq 'Path') { continue }
            [Environment]::SetEnvironmentVariable([string]$name, [string]$vars[$name], 'Process')
        }
    }
    $machinePath = [Environment]::GetEnvironmentVariable('Path','Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path','User')
    $env:Path = "$machinePath;$userPath"
}

try {
    Import-WindowsEnvironment
    if (-not (Test-Path -LiteralPath $startScript)) {
        throw "Missing canonical starter: $startScript"
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $startScript -SkipCloudflared
    if ($LASTEXITCODE -ne 0) {
        throw "start-mcp.ps1 exit=$LASTEXITCODE"
    }
    Write-BootstrapLog "Canonical Windows-native edgars-mcp startup completed."
}
catch {
    Write-BootstrapLog "Startup failed: $($_.Exception.Message)"
    exit 1
}
