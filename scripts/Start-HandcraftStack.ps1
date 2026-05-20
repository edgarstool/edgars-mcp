param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.whoasked.vip/mcp",
    [string]$CloudflaredConfig = "$env:USERPROFILE\.cloudflared\config.yml",
    [int]$WaitSeconds = 30,
    [switch]$SkipCloudflared,
    [switch]$SkipPublic
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$ServerPath = Join-Path $RepoRoot "server_http.py"
$LogDir = Join-Path $RepoRoot "logs"
$HttpOutLogPath = Join-Path $LogDir "handcraft-http.out.log"
$HttpErrLogPath = Join-Path $LogDir "handcraft-http.err.log"
$CloudflaredOutLogPath = Join-Path $LogDir "cloudflared.out.log"
$CloudflaredErrLogPath = Join-Path $LogDir "cloudflared.err.log"
$HealthScript = Join-Path $RepoRoot "scripts\Test-HandcraftHealth.ps1"
$LocalHealthUrl = "$($LocalBaseUrl.TrimEnd('/'))/health"

function Test-LocalHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $LocalHealthUrl -TimeoutSec 3
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-Until {
    param(
        [scriptblock]$Probe,
        [string]$Name
    )

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Probe) {
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "Timed out waiting for $Name after $WaitSeconds seconds."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if (-not (Test-LocalHealth)) {
    $doppler = Get-Command doppler -ErrorAction Stop
    $py = Get-Command py -ErrorAction Stop
    $args = @(
        "run",
        "--project", "handcraft-mcp",
        "--config", "prd",
        "--",
        $py.Source,
        "-3",
        $ServerPath
    )

    Start-Process `
        -FilePath $doppler.Source `
        -ArgumentList $args `
        -WorkingDirectory $RepoRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $HttpOutLogPath `
        -RedirectStandardError $HttpErrLogPath

    Wait-Until -Name "local handcraft health at $LocalHealthUrl" -Probe { Test-LocalHealth }
}

if (-not $SkipCloudflared) {
    $cloudflaredProcess = Get-Process cloudflared -ErrorAction SilentlyContinue
    if (-not $cloudflaredProcess) {
        if (-not (Test-Path -LiteralPath $CloudflaredConfig)) {
            throw "Cloudflared config not found: $CloudflaredConfig"
        }
        $cloudflared = Get-Command cloudflared -ErrorAction Stop
        Start-Process `
            -FilePath $cloudflared.Source `
            -ArgumentList @("tunnel", "--config", $CloudflaredConfig, "run") `
            -WorkingDirectory $RepoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $CloudflaredOutLogPath `
            -RedirectStandardError $CloudflaredErrLogPath
    }
}

$healthArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $HealthScript,
    "-LocalBaseUrl", $LocalBaseUrl,
    "-PublicMcpUrl", $PublicMcpUrl,
    "-TimeoutSec", "10"
)
if ($SkipPublic) {
    $healthArgs += "-SkipPublic"
}

& powershell @healthArgs
