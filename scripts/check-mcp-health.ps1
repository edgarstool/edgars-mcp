<#
.SYNOPSIS
  MCP 服務健康檢查（5 層 cascade）。
  5-layer cascade health check: process → port → TCP → HTTP → tunnel.

.DESCRIPTION
  檢查層次（依序執行，前層失敗則後續層標記為 skip）：
    1. process  — handcraft-http python 行程存活（PID file 或 port owner）
    2. port     — :8765 由 netstat 確認 LISTENING
    3. tcp      — TCP 實際連線 127.0.0.1:8765
    4. http     — GET /health 回傳 200
    5. tunnel   — cloudflared 行程存活 + 可選 public MCP 端點可達

  輸出：
    - healthcheck-summary.json（RuntimeRoot / G:\AI_WORK_512\run\mcp-handcraft\）
    - healthcheck.log（RepoLogDir / logs\）
    - 連續失敗 ≥ AlertThreshold 次時，summary.alert = true；exit 2

  Exit code:
    0 — 全部通過
    1 — 有失敗（未觸發告警閾值）
    2 — 連續失敗達告警閾值

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp-health.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp-health.ps1 -SkipPublic -AlertThreshold 5
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl    = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl    = "https://mcp.edgars.tools/mcp",
    [int]$Port               = 8765,
    [int]$TimeoutSec         = 10,
    [int]$AlertThreshold     = 3,
    [switch]$SkipPublic,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

# ── Module & config ───────────────────────────────────────────────────────────
$modulePath = Join-Path $PSScriptRoot "Handcraft-McpCommon.psm1"
Import-Module $modulePath -Force

$config = Get-HandcraftConfig -Port $Port -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl

$summaryFile = Join-Path $config.RuntimeRoot "healthcheck-summary.json"
$stateFile   = Join-Path $config.RuntimeRoot "healthcheck-state.json"
$logFile     = Join-Path $config.RepoLogDir  "healthcheck.log"

# ── Ensure dirs exist ─────────────────────────────────────────────────────────
foreach ($dir in @($config.RuntimeRoot, $config.RepoLogDir)) {
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

# ── Helpers ───────────────────────────────────────────────────────────────────
function New-LayerResult {
    param(
        [string]$Name,
        [bool]$Ok,
        [hashtable]$Extra = @{},
        [string]$Status = $null   # "pass" | "fail" | "skip"
    )
    $r = [ordered]@{ name = $Name; ok = $Ok }
    if ($Status) { $r.status = $Status } else { $r.status = if ($Ok) { "pass" } else { "fail" } }
    foreach ($k in $Extra.Keys) { $r[$k] = $Extra[$k] }
    return $r
}

function New-SkipResult {
    param([string]$Name, [string]$Reason)
    return [ordered]@{ name = $Name; ok = $null; status = "skip"; skip_reason = $Reason }
}

function Test-TcpConnect {
    param([string]$HostName = "127.0.0.1", [int]$TcpPort, [int]$TimeoutMs = 3000)
    try {
        $sw     = [System.Diagnostics.Stopwatch]::StartNew()
        $client = [System.Net.Sockets.TcpClient]::new()
        $task   = $client.ConnectAsync($HostName, $TcpPort)
        $done   = $task.Wait($TimeoutMs)
        $sw.Stop()
        $client.Close()
        if ($done -and -not $task.IsFaulted) {
            return @{ ok = $true; latency_ms = [int]$sw.ElapsedMilliseconds }
        }
        return @{ ok = $false; latency_ms = $null; error = "timeout" }
    } catch {
        return @{ ok = $false; latency_ms = $null; error = $_.Exception.Message }
    }
}

function Read-StateFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return @{ consecutive_failures = 0 }
    }
    try {
        $raw = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        return @{ consecutive_failures = [int]$raw.consecutive_failures }
    } catch {
        return @{ consecutive_failures = 0 }
    }
}

function Write-StateFile {
    param([string]$Path, [int]$ConsecutiveFailures)
    [ordered]@{
        consecutive_failures = $ConsecutiveFailures
        updated_at           = (Get-Date).ToString("o")
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Append-Log {
    param([string]$Path, [string]$Line)
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content -LiteralPath $Path -Value "[$ts] $Line" -Encoding UTF8
}

# ── Run 5-layer cascade ───────────────────────────────────────────────────────
$layers     = [ordered]@{}
$passCount  = 0
$failCount  = 0
$skipCount  = 0
$cascadeOk  = $true   # set to false once a layer fails; subsequent layers become skip

# Layer 1 — process ────────────────────────────────────────────────────────────
$pidFromFile = Read-HandcraftPidFile -Path $config.HttpPidFile
$ownerPid    = Get-PortOwnerPid -Port $config.Port
$procPid     = if ($pidFromFile -and (Test-ProcessAlive -ProcessId $pidFromFile)) {
    $pidFromFile
} elseif ($ownerPid -and (Test-ProcessAlive -ProcessId $ownerPid)) {
    $ownerPid
} else {
    $null
}
$procOk = [bool]$procPid

$l1 = New-LayerResult -Name "process" -Ok $procOk -Extra @{
    pid          = $procPid
    pid_from_file = $pidFromFile
    port_owner   = $ownerPid
}
$layers.process = $l1

if ($procOk) { $passCount++ } else { $failCount++; $cascadeOk = $false }

# Layer 2 — port ───────────────────────────────────────────────────────────────
if ($cascadeOk) {
    $portOk = Test-PortListening -Port $config.Port
    $l2     = New-LayerResult -Name "port" -Ok $portOk -Extra @{ port = $config.Port; owner_pid = $ownerPid }
    if ($portOk) { $passCount++ } else { $failCount++; $cascadeOk = $false }
} else {
    $l2 = New-SkipResult -Name "port" -Reason "process_failed"
    $skipCount++
}
$layers.port = $l2

# Layer 3 — tcp ────────────────────────────────────────────────────────────────
if ($cascadeOk) {
    $tcpResult = Test-TcpConnect -HostName "127.0.0.1" -TcpPort $config.Port -TimeoutMs ($TimeoutSec * 1000)
    $l3 = New-LayerResult -Name "tcp" -Ok $tcpResult.ok -Extra @{
        host       = "127.0.0.1"
        port       = $config.Port
        latency_ms = $tcpResult.latency_ms
        error      = $tcpResult.error
    }
    if ($l3.ok) { $passCount++ } else { $failCount++; $cascadeOk = $false }
} else {
    $l3 = New-SkipResult -Name "tcp" -Reason "port_failed_or_skipped"
    $skipCount++
}
$layers.tcp = $l3

# Layer 4 — http ───────────────────────────────────────────────────────────────
if ($cascadeOk) {
    $httpProbe = Invoke-HandcraftHttpProbe -Name "health" -Uri $config.LocalHealthUrl -TimeoutSec $TimeoutSec
    $l4 = New-LayerResult -Name "http" -Ok $httpProbe.ok -Extra @{
        url    = $config.LocalHealthUrl
        status = $httpProbe.status
        error  = $httpProbe.error
    }
    if ($l4.ok) { $passCount++ } else { $failCount++; $cascadeOk = $false }
} else {
    $l4 = New-SkipResult -Name "http" -Reason "tcp_failed_or_skipped"
    $skipCount++
}
$layers.http = $l4

# Layer 5 — tunnel ─────────────────────────────────────────────────────────────
if ($cascadeOk) {
    $cfProc       = [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
    $publicStatus = $null
    $publicError  = $null
    $publicOk     = $cfProc   # baseline: tunnel = cloudflared alive

    if (-not $SkipPublic -and $cfProc) {
        $pub = Invoke-HandcraftHttpProbe -Name "public_mcp" -Uri $config.PublicMcpUrl -TimeoutSec $TimeoutSec
        # 401/403/405 means reachable but auth-gated — still counts as tunnel OK
        if ($pub.ok -or ($pub.status -in @(401, 403, 405))) {
            $publicOk = $true
        } else {
            $publicOk = $false
        }
        $publicStatus = $pub.status
        $publicError  = $pub.error
    }

    $l5 = New-LayerResult -Name "tunnel" -Ok $publicOk -Extra @{
        cloudflared_process = $cfProc
        public_url          = if ($SkipPublic) { $null } else { $config.PublicMcpUrl }
        public_status       = $publicStatus
        public_error        = $publicError
        skip_public         = [bool]$SkipPublic
    }
    if ($l5.ok) { $passCount++ } else { $failCount++ }
} else {
    $l5 = New-SkipResult -Name "tunnel" -Reason "http_failed_or_skipped"
    $skipCount++
}
$layers.tunnel = $l5

# ── Overall result ─────────────────────────────────────────────────────────────
$overallOk = ($failCount -eq 0)

# ── Consecutive failure tracking ───────────────────────────────────────────────
$state = Read-StateFile -Path $stateFile
if ($overallOk) {
    $consecutiveFailures = 0
} else {
    $consecutiveFailures = $state.consecutive_failures + 1
}
Write-StateFile -Path $stateFile -ConsecutiveFailures $consecutiveFailures

$alert = $consecutiveFailures -ge $AlertThreshold

# ── Build summary ──────────────────────────────────────────────────────────────
$summary = [ordered]@{
    ok                   = $overallOk
    alert                = $alert
    consecutive_failures = $consecutiveFailures
    alert_threshold      = $AlertThreshold
    pass                 = $passCount
    fail                 = $failCount
    skip                 = $skipCount
    local_base_url       = $config.LocalBaseUrl
    public_mcp_url       = if ($SkipPublic) { $null } else { $config.PublicMcpUrl }
    checked_at           = (Get-Date).ToString("o")
    layers               = $layers
}

# ── Write JSON summary ─────────────────────────────────────────────────────────
$summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryFile -Encoding UTF8

# ── Write log ──────────────────────────────────────────────────────────────────
$statusText = if ($overallOk) { "OK" } elseif ($alert) { "ALERT" } else { "FAIL" }
$logLine    = "status=$statusText pass=$passCount fail=$failCount skip=$skipCount consecutive=$consecutiveFailures"
Append-Log -Path $logFile -Line $logLine

# ── Console output ─────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== check-mcp-health ==="
foreach ($name in $layers.Keys) {
    $layer  = $layers[$name]
    $symbol = switch ($layer.status) {
        "pass" { "[PASS]" }
        "fail" { "[FAIL]" }
        "skip" { "[SKIP]" }
        default { "[?]  " }
    }
    $detail = if ($layer.skip_reason) { "  skip_reason=$($layer.skip_reason)" } else { "" }
    Write-Host ("{0} {1}{2}" -f $symbol, $name, $detail)
}
Write-Host ""
Write-Host ("pass=$passCount  fail=$failCount  skip=$skipCount  consecutive_failures=$consecutiveFailures")
if ($alert) {
    Write-Host "*** ALERT: consecutive failures reached threshold ($AlertThreshold) ***" -ForegroundColor Red
}
Write-Host ""
Write-Host "summary => $summaryFile"

# ── Exit ───────────────────────────────────────────────────────────────────────
if ($alert)      { exit 2 }
if (-not $overallOk) { exit 1 }
exit 0
