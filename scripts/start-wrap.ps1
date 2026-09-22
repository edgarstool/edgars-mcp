<#
.SYNOPSIS
  啟動 edgars-mcp HTTP，並套用 wrap-profile（Windows native，無 Docker / 1Password）。

.DESCRIPTION
  - 讀取 wrap-profile.json 的 MCP_WRAP_* 旗標
  - 強制重啟 HTTP（除非 -NoForce）
  - 預設不碰 cloudflared；加 -StartCloudflared 才會動

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-wrap.ps1 -ProfileJson G:\AI_WORK_512\run\mcp-handcraft\wrap-profile.json
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [int]$Port = 8765,
    [int]$WaitSeconds = 30,
    [switch]$NoForce,
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
        "MCP_WRAP_OPENMONTAGE",
        "MCP_WRAP_HERMES",
        "MCP_WRAP_OPENCLAW"
    )
    $extra = [ordered]@{}
    foreach ($key in $keys) { $extra[$key] = "0" }

    if (-not $Path -or -not (Test-Path -LiteralPath $Path)) {
        $extra["MCP_WRAP_PLAYWRIGHT"] = "1"
        $extra["MCP_WRAP_WINDOWS"] = "1"
        $extra["MCP_WRAP_DESKTOP_COMMANDER"] = "1"
        $extra["MCP_WRAP_DESCOPE"] = "1"
        $extra["MCP_WRAP_CLOUDFLARED"] = "1"
        $extra["MCP_WRAP_OPENMONTAGE"] = "1"
        $extra["MCP_WRAP_HERMES"] = "1"
        $extra["MCP_WRAP_OPENCLAW"] = "1"
        return @{ env = $extra; source = "default-native"; mode = "local" }
    }

    $raw = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
    $flags = $raw.flags
    if ($null -eq $flags) { $flags = $raw }
    foreach ($key in $keys) {
        $val = $null
        if ($flags.PSObject.Properties.Name -contains $key) {
            $val = [string]$flags.$key
        }
        $extra[$key] = if ($val -match '^(1|true|yes|on)$') { "1" } else { "0" }
    }
    $extra["MCP_WRAP_OP_CONNECT"] = "0"
    $mode = if ($raw.mode) { [string]$raw.mode } else { "custom" }
    return @{ env = $extra; source = $Path; mode = $mode }
}

Write-Host "[start-wrap] repo=$($config.RepoRoot)"
Write-Host "[start-wrap] health=$($config.LocalHealthUrl)"
Write-Host "[start-wrap] mode=native (no Docker / no 1Password Connect)"

$profileInfo = Read-WrapProfileEnv -Path $ProfileJson
$extraEnv = @{}
foreach ($key in $profileInfo.env.Keys) {
    $extraEnv[$key] = $profileInfo.env[$key]
}
Write-Host "[start-wrap] profile=$($profileInfo.source) mode=$($profileInfo.mode)"
Write-Host ("[start-wrap] wraps=" + (($extraEnv.GetEnumerator() | Sort-Object Name | ForEach-Object { "$($_.Key)=$($_.Value)" }) -join " "))

$forceRestart = -not $NoForce
$httpResult = Start-HandcraftHttpServer -Config $config -Force:$forceRestart -ExtraEnv $extraEnv
if ($httpResult.already_running) {
    Write-Host "[start-wrap] HTTP already healthy (pid=$($httpResult.pid)). wrap 可能仍是舊的；要套用請不要加 -NoForce。"
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

[ordered]@{
    ok           = $true
    action       = "start-wrap"
    mode         = "native"
    wraps        = $extraEnv
    profile      = $profileInfo.source
    profile_mode = $profileInfo.mode
    force        = $forceRestart
    http         = $httpResult
    cloudflared  = $tunnelResult
    pid_file     = $config.HttpPidFile
    checked_at   = (Get-Date).ToString("o")
} | ConvertTo-Json -Depth 6

exit 0
