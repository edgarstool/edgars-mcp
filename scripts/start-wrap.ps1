<#
.SYNOPSIS
  啟動 edgars-mcp HTTP，並打開全功能 wrap 層（預設遠端仍關）。
  Start edgars-mcp HTTP with wrap tools enabled (remote wrap stays off).

.DESCRIPTION
  - 先確認 1Password Connect :8877；必要時 docker compose up -d。
  - 預設 Force 重啟 HTTP，讓 MCP_WRAP_ALL=1 寫進 launcher。
  - 預設不碰 cloudflared（正式 tunnel 可能已在跑）。
  - 不把 token 寫進桌面腳本。

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-wrap.ps1
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [int]$Port = 8765,
    [int]$WaitSeconds = 30,
    [string]$ConnectDir = "V:\projects\1password-connet",
    [switch]$NoForce,
    [switch]$SkipConnect,
    [switch]$StartCloudflared,
    [string]$ProfileJson = "G:\AI_WORK_512\run\mcp-handcraft\wrap-profile.json",
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

$modulePath = Join-Path $PSScriptRoot "Handcraft-McpCommon.psm1"
Import-Module $modulePath -Force

$config = Get-HandcraftConfig -Port $Port -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl
$config | Add-Member -NotePropertyName WaitSeconds -NotePropertyValue $WaitSeconds -Force

function Test-ConnectHealth {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8877/health" -TimeoutSec 3
        return ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300)
    } catch {
        return $false
    }
}

function Ensure-OpConnect {
    param([string]$Dir)

    if (Test-ConnectHealth) {
        return [pscustomobject]@{ ok = $true; already_running = $true; action = "skip" }
    }

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "docker 不在 PATH。請先開 Docker Desktop 再重跑啟動。"
    }

    docker info 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $dd = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if (Test-Path -LiteralPath $dd) {
            Write-Host "[start-wrap] Docker engine 未就緒，嘗試啟動 Docker Desktop..."
            Start-Process -FilePath $dd
            $deadline = (Get-Date).AddMinutes(4)
            do {
                Start-Sleep -Seconds 5
                docker info 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { break }
            } while ((Get-Date) -lt $deadline)
        }
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Docker engine 仍未就緒，無法啟動 1Password Connect。"
        }
    }

    $compose = $null
    foreach ($name in @("docker-compose.yaml", "docker-compose.yml")) {
        $candidate = Join-Path $Dir $name
        if (Test-Path -LiteralPath $candidate) {
            $compose = $candidate
            break
        }
    }
    if (-not $compose) {
        throw "找不到 Connect compose：$Dir"
    }

    Write-Host "[start-wrap] Connect 未健康，執行 docker compose up -d"
    Push-Location $Dir
    try {
        docker compose -f (Split-Path -Leaf $compose) up -d
        if ($LASTEXITCODE -ne 0) {
            throw "docker compose up -d 失敗（exit $LASTEXITCODE）"
        }
    } finally {
        Pop-Location
    }

    $readyDeadline = (Get-Date).AddSeconds(40)
    do {
        if (Test-ConnectHealth) {
            return [pscustomobject]@{ ok = $true; already_running = $false; action = "compose_up" }
        }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $readyDeadline)

    throw "Connect compose 已啟動，但 http://127.0.0.1:8877/health 仍未通過。"
}

function Read-WrapProfileEnv {
    param([string]$Path)

    $keys = @(
        "MCP_WRAP_ALL",
        "MCP_WRAP_ALLOW_REMOTE",
        "MCP_WRAP_PLAYWRIGHT",
        "MCP_WRAP_WINDOWS",
        "MCP_WRAP_DESKTOP_COMMANDER",
        "MCP_WRAP_DESCOPE",
        "MCP_WRAP_CLOUDFLARED",
        "MCP_WRAP_OP_CONNECT",
        "MCP_WRAP_OPENMONTAGE",
        "MCP_WRAP_HERMES",
        "MCP_WRAP_OPENCLAW"
    )
    $extra = [ordered]@{}
    foreach ($key in $keys) { $extra[$key] = "0" }

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        $extra["MCP_WRAP_ALL"] = "1"
        $extra["MCP_WRAP_ALLOW_REMOTE"] = "0"
        return @{ env = $extra; source = "default-all"; mode = "full" }
    }

    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $flags = $raw.flags
    if ($null -eq $flags) { $flags = $raw }
    foreach ($key in $keys) {
        $val = $null
        if ($flags.PSObject.Properties.Name -contains $key) {
            $val = [string]$flags.$key
        }
        if ($val -match '^(1|true|yes|on)$') {
            $extra[$key] = "1"
        } else {
            $extra[$key] = "0"
        }
    }
    $mode = "custom"
    if ($raw.mode) { $mode = [string]$raw.mode }
    return @{ env = $extra; source = $Path; mode = $mode }
}

Write-Host "[start-wrap] repo=$($config.RepoRoot)"
Write-Host "[start-wrap] health=$($config.LocalHealthUrl)"

$profileInfo = Read-WrapProfileEnv -Path $ProfileJson
$extraEnv = @{}
foreach ($key in $profileInfo.env.Keys) {
    $extraEnv[$key] = $profileInfo.env[$key]
}
Write-Host "[start-wrap] profile=$($profileInfo.source) mode=$($profileInfo.mode)"
Write-Host ("[start-wrap] wraps=" + (($extraEnv.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join " "))

$connectResult = $null
if (-not $SkipConnect) {
    $connectResult = Ensure-OpConnect -Dir $ConnectDir
    if ($connectResult.already_running) {
        Write-Host "[start-wrap] 1Password Connect already healthy (:8877)."
    } else {
        Write-Host "[start-wrap] 1Password Connect started."
    }
}

$forceRestart = -not $NoForce
$httpResult = Start-HandcraftHttpServer -Config $config -Force:$forceRestart -ExtraEnv $extraEnv
if ($httpResult.already_running) {
    Write-Host "[start-wrap] HTTP already healthy (pid=$($httpResult.pid)). wrap 環境可能仍是舊的；要套用 wrap 請不要加 -NoForce。"
} else {
    Write-Host "[start-wrap] HTTP started (pid=$($httpResult.pid))."
}

$tunnelResult = $null
if ($StartCloudflared) {
    $tunnelResult = Start-HandcraftCloudflared -Config $config
    if ($tunnelResult.already_running) {
        Write-Host "[start-wrap] cloudflared already running (pid=$($tunnelResult.pid))."
    } else {
        Write-Host "[start-wrap] cloudflared started (pid=$($tunnelResult.pid))."
    }
} else {
    Write-Host "[start-wrap] skipped cloudflared (production tunnel untouched)."
}

$result = [ordered]@{
    ok          = $true
    action      = "start-wrap"
    wraps       = $extraEnv
    profile     = $profileInfo.source
    mode        = $profileInfo.mode
    force       = $forceRestart
    connect     = $connectResult
    http        = $httpResult
    cloudflared = $tunnelResult
    pid_file    = $config.HttpPidFile
    checked_at  = (Get-Date).ToString("o")
}

$result | ConvertTo-Json -Depth 6
exit 0
