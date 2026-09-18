param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [string]$TunnelName = "edgar-local-01-tunnel",
    [int]$WaitSeconds = 30,
    [switch]$SkipCloudflared,
    [switch]$SkipPublic
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$StartMcp = Join-Path $RepoRoot "scripts\start-mcp.ps1"
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

if (-not (Test-LocalHealth)) {
    if (-not (Test-Path -LiteralPath $StartMcp)) {
        throw "Missing start script: $StartMcp"
    }
    $args = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", $StartMcp,
        "-LocalBaseUrl", $LocalBaseUrl,
        "-PublicMcpUrl", $PublicMcpUrl,
        "-WaitSeconds", "$WaitSeconds",
        "-SkipCloudflared"
    )
    & powershell.exe @args
    if (-not (Test-LocalHealth)) {
        throw "Timed out waiting for local handcraft health at $LocalHealthUrl"
    }
}

if (-not $SkipCloudflared) {
    $cloudflaredService = Get-Service Cloudflared -ErrorAction SilentlyContinue
    $cloudflaredProcess = Get-Process cloudflared -ErrorAction SilentlyContinue
    if ($cloudflaredService -and $cloudflaredService.Status -eq "Running") {
        Write-Verbose "Cloudflared Windows service is already running; skipping manual tunnel start."
    } elseif (-not $cloudflaredProcess) {
        $cloudflared = Get-Command cloudflared -ErrorAction Stop
        $LogDir = Join-Path $RepoRoot "logs"
        New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
        Start-Process `
            -FilePath $cloudflared.Source `
            -ArgumentList @("tunnel", "run", $TunnelName) `
            -WorkingDirectory $RepoRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $LogDir "cloudflared.out.log") `
            -RedirectStandardError (Join-Path $LogDir "cloudflared.err.log")
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
