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
Import-Module (Join-Path $RepoRoot "scripts\Handcraft-McpCommon.psm1") -Force
$config = Get-HandcraftConfig -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl
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
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    $pythonArgs = @("-3", $ServerPath)
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python -ErrorAction Stop
        $pythonArgs = @($ServerPath)
    }

    $args = @(
        "run",
        "--project", "handcraft-mcp",
        "--config", "prd",
        "--",
        $pythonCommand.Source
    ) + $pythonArgs

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
    $null = Start-HandcraftCloudflared -Config $config
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
