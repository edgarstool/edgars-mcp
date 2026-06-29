$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$stackScript = Join-Path $repoRoot "scripts\Start-HandcraftStack.ps1"
$outLogPath = Join-Path $repoRoot "mcp-http-startup-stack.out.log"
$errLogPath = Join-Path $repoRoot "mcp-http-startup-stack.err.log"
$bootstrapLog = Join-Path $repoRoot "mcp-http-startup.log"

function Write-BootstrapLog {
    param([string] $Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $bootstrapLog -Value "[$timestamp] $Message"
}

try {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"

    if (-not (Test-Path -LiteralPath $stackScript)) {
        Write-BootstrapLog "Missing stack script: $stackScript."
        exit 1
    }

    $missing = @()
    foreach ($commandName in @("doppler", "python", "cloudflared")) {
        if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
            $missing += $commandName
        }
    }
    if ($missing.Count -gt 0) {
        Write-BootstrapLog "Missing runtime command(s): $($missing -join ', ')."
        exit 1
    }

    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $stackScript
    )
    Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList $args `
        -WorkingDirectory $repoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $outLogPath `
        -RedirectStandardError $errLogPath

    Write-BootstrapLog "Started handcraft stack via Start-HandcraftStack.ps1."
}
catch {
    Write-BootstrapLog "Startup failed: $($_.Exception.Message)"
    exit 1
}
