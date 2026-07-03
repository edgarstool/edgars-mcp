<#
.SYNOPSIS
  MCP 服務穩定性監控 — 檢查腳本（check-and-report only，不重啟）。
  Cascade: process → port → TCP → HTTP → tunnel
  連續失敗 3 次才寫入 failure count（避免暫時性抖動）。

.DESCRIPTION
  檢查分層 cascade，任一層失敗即停止向下一層前進。
  輸出：JSON（healthcheck-summary.json）+ 同時寫入文字 log。
  與 restart-mcp.ps1 完全分離：此腳本只讀 / 寫狀態，不執行重啟。

  Cascade 等級（由淺入深）：
    1. process  — 程序是否存在
    2. port     — 指定 port 是否在 LISTEN
    3. tcp      — TCP handshake 是否可達（目標 IP:Port）
    4. http     — HTTP GET /health 是否 2xx
    5. tunnel   — cloudflared tunnel 是否運行（外網可達）

  輸出檔：
    $(RuntimeRoot)\healthcheck-summary.json
    $(RepoLogDir)\healthcheck-YYYYMMDD.log

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp-health.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp-health.ps1 -Port 8765 -LocalBaseUrl http://127.0.0.1:8765
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\check-mcp-health.ps1 -SkipPublic -FailureCountPath "C:\path\to\fail.json"
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl  = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl  = "https://mcp.edgars.tools/mcp",
    [int]$Port             = 8765,
    [int]$TimeoutSec       = 8,
    [switch]$SkipPublic,
    [switch]$SkipTunnel,
    [string]$FailureCountPath = "",   # 空字串 = 自動路徑
    [switch]$Help
)

$ErrorActionPreference = "Continue"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

# ── 路徑推導 ───────────────────────────────────────────────────────────────────
$RepoRoot     = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot  = "G:\AI_WORK_512\run\mcp-handcraft"
$RepoLogDir   = Join-Path $RepoRoot "logs"
$SummaryJson  = Join-Path $RuntimeRoot "healthcheck-summary.json"
$FailCountFile = if ($FailureCountPath) { $FailureCountPath } else { Join-Path $RuntimeRoot "consecutive-failures.json" }

$todayLog = Join-Path $RepoLogDir ("healthcheck-" + (Get-Date -Format "yyyyMMdd") + ".log")

Import-Module (Join-Path $PSScriptRoot "Handcraft-McpCommon.psm1") -Force

function Write-Log {
    param([Parameter(ValueFromPipeline)][string]$Msg, [string]$Level = "INFO")
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] [$Level] $Msg"
    # console
    switch ($Level) {
        "ERROR" { Write-Host $line -ForegroundColor Red }
        "WARN"  { Write-Host $line -ForegroundColor Yellow }
        "OK"    { Write-Host $line -ForegroundColor Green }
        default { Write-Host $line }
    }
    # file (append)
    $dir = Split-Path -Parent $todayLog
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Add-Content -LiteralPath $todayLog -Value $line -Encoding UTF8
}

# ── 共用 helpers（內嵌，避免模組載入失敗） ─────────────────────────────────────
function Test-CommandAvailable {
    param([string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Get-NetstatPid {
    param([int]$Port)
    $line = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING" | Select-Object -First 1
    if (-not $line) { return $null }
    $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
    $pidText = $parts[-1]
    if ($pidText -match '^\d+$') { return [int]$pidText }
    return $null
}

function Test-TcpPort {
    param([string]$Hostname, [int]$TcpPort, [int]$Sec = 5)
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async  = $client.BeginConnect($Hostname, $TcpPort, $null, $null)
        $wait   = $async.AsyncWaitHandle.WaitOne($Sec * 1000, $false)
        if ($wait -and $client.Connected) {
            $client.Close()
            return $true
        }
        $client.Close()
    } catch { }
    return $false
}

function Invoke-CascadeCheck {
    param(
        [int]$Port,
        [string]$LocalBaseUrl,
        [string]$PublicMcpUrl,
        [int]$TimeoutSec,
        [bool]$SkipPublic,
        [bool]$SkipTunnel
    )

    $base = $LocalBaseUrl.TrimEnd('/')
    $healthUri = "$base/health"
    $mcpUri    = "$base/mcp"

    $result = [ordered]@{
        checkedAt          = (Get-Date).ToString("o")
        host               = $env:COMPUTERNAME
        port               = $Port
        localBaseUrl       = $LocalBaseUrl
        publicMcpUrl       = if ($SkipPublic) { $null } else { $PublicMcpUrl }
        cascade            = [ordered]@{}
        consecutiveFails   = 0
        overallOk          = $false
        shouldAlert        = $false
    }

    # ── 等級 1：程序 ─────────────────────────────────────────────────────────
    $procName  = "python"
    $procRunning = $null -ne (Get-Process python -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -like "*server_http*" -or $_.CommandLine -like "*mcp*handcraft*"
    } | Select-Object -First 1)

    # fallback: 任意 python 行程 + port owner pid
    if (-not $procRunning) {
        $ownerPid = Get-NetstatPid -Port $Port
        $procRunning = $null -ne (Get-Process -Id $ownerPid -ErrorAction SilentlyContinue)
    }

    $result.cascade.process = [ordered]@{
        level    = 1
        name     = "process"
        ok       = $procRunning
        detail   = if ($procRunning) { "python process alive" } else { "no python/mcp process found" }
    }

    if (-not $procRunning) {
        $result.cascade.tcp      = [ordered]@{ level = 2; name = "tcp";      ok = $null; detail = "skipped (process check failed)" }
        $result.cascade.http      = [ordered]@{ level = 3; name = "http";     ok = $null; detail = "skipped (process check failed)" }
        $result.cascade.tunnel    = [ordered]@{ level = 4; name = "tunnel";   ok = $null; detail = "skipped (process check failed)" }
        return $result
    }

    # ── 等級 2：Port listen ──────────────────────────────────────────────────
    $portListening = $null -ne (Get-NetstatPid -Port $Port)
    $ownerPid = Get-NetstatPid -Port $Port

    $result.cascade.port = [ordered]@{
        level      = 2
        name       = "port"
        ok         = $portListening
        port       = $Port
        ownerPid   = $ownerPid
        detail     = if ($portListening) { "port $Port is LISTENING (PID $ownerPid)" } else { "port $Port not listening" }
    }

    if (-not $portListening) {
        $result.cascade.tcp      = [ordered]@{ level = 3; name = "tcp";    ok = $null; detail = "skipped (port check failed)" }
        $result.cascade.http      = [ordered]@{ level = 4; name = "http";   ok = $null; detail = "skipped (port check failed)" }
        $result.cascade.tunnel    = [ordered]@{ level = 5; name = "tunnel"; ok = $null; detail = "skipped (port check failed)" }
        return $result
    }

    # ── 等級 3：TCP handshake ─────────────────────────────────────────────────
    $tcpOk   = $false
    $tcpHost = "127.0.0.1"
    $tcpPort = $Port

    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $async  = $client.BeginConnect($tcpHost, $tcpPort, $null, $null)
        $wait   = $async.AsyncWaitHandle.WaitOne($TimeoutSec * 1000, $false)
        $tcpOk  = $wait -and $client.Connected
        $client.Close()
    } catch {
        $tcpOk = $false
    }

    $result.cascade.tcp = [ordered]@{
        level    = 3
        name     = "tcp"
        ok       = $tcpOk
        host     = $tcpHost
        port     = $tcpPort
        detail   = if ($tcpOk) { "TCP $tcpHost`:$tcpPort reachable" } else { "TCP $tcpHost`:$tcpPort unreachable" }
    }

    if (-not $tcpOk) {
        $result.cascade.http   = [ordered]@{ level = 4; name = "http";   ok = $null; detail = "skipped (TCP check failed)" }
        $result.cascade.tunnel = [ordered]@{ level = 5; name = "tunnel"; ok = $null; detail = "skipped (TCP check failed)" }
        return $result
    }

    # ── 等級 4：HTTP /health ───────────────────────────────────────────────────
    $httpOk   = $false
    $httpStatus = $null
    $httpDetail = ""

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $healthUri -TimeoutSec $TimeoutSec -DisableKeepAlive
        $httpStatus = [int]$response.StatusCode
        $httpOk = $httpStatus -ge 200 -and $httpStatus -lt 300
        $httpDetail = "HTTP $httpStatus"
    } catch {
        if ($_.Exception.Response) {
            $httpStatus = [int]$_.Exception.Response.StatusCode
            $httpDetail = "HTTP $httpStatus"
        } else {
            $httpDetail = $_.Exception.Message
        }
    }

    $result.cascade.http = [ordered]@{
        level     = 4
        name      = "http"
        ok        = $httpOk
        uri       = $healthUri
        status    = $httpStatus
        detail    = $httpDetail
    }

    if (-not $httpOk) {
        $result.cascade.tunnel = [ordered]@{ level = 5; name = "tunnel"; ok = $null; detail = "skipped (HTTP check failed)" }
        return $result
    }

    # ── 等級 5：Tunnel（cloudflared + public URL） ───────────────────────────
    if ($SkipTunnel -or $SkipPublic) {
        $result.cascade.tunnel = [ordered]@{
            level  = 5
            name   = "tunnel"
            ok     = $null
            detail = "skipped (SkipTunnel or SkipPublic flag)"
        }
    } else {
        $deprecatedCloudflared = @(Get-CloudflaredProcessDetails | Where-Object { $_.uses_deprecated_config })
        if ($deprecatedCloudflared.Count -gt 0) {
            $stopped = @(Stop-DeprecatedCloudflaredProcesses)
            if ($stopped.Count -gt 0) {
                Start-Sleep -Seconds 2
            }
        }
        $cloudflaredOk = Test-HandcraftCloudflaredHealthy
        $publicOk = $false
        $publicStatus = $null
        $publicDetail = ""

        try {
            $pubResp = Invoke-WebRequest -UseBasicParsing -Uri $PublicMcpUrl -TimeoutSec $TimeoutSec -DisableKeepAlive
            $publicStatus = [int]$pubResp.StatusCode
            # 401/403/405 = auth block 但 tunnel 可達，算部分成功
            $publicOk = $publicStatus -lt 500
            $publicDetail = "HTTP $publicStatus"
        } catch {
            if ($_.Exception.Response) {
                $publicStatus = [int]$_.Exception.Response.StatusCode
                $publicDetail = "HTTP $publicStatus"
            } else {
                $publicDetail = $_.Exception.Message
            }
        }

        $result.cascade.tunnel = [ordered]@{
            level            = 5
            name             = "tunnel"
            ok               = $cloudflaredOk -and $publicOk
            cloudflaredProc  = $cloudflaredOk
            publicUrl        = $PublicMcpUrl
            publicStatus     = $publicStatus
            deprecatedProc   = @($deprecatedCloudflared | ForEach-Object { $_.pid })
            detail           = "cloudflaredHealthy=$cloudflaredOk, public=$publicDetail"
        }
    }

    return $result
}

# ── 主程式 ───────────────────────────────────────────────────────────────────
Write-Log "=== MCP Health Check Started ==="
Write-Log "RepoRoot: $RepoRoot"
Write-Log "RuntimeRoot: $RuntimeRoot"
Write-Log "Port: $Port / LocalBaseUrl: $LocalBaseUrl / PublicMcpUrl: $PublicMcpUrl"

# 執行 cascade 檢查
$checkResult = Invoke-CascadeCheck -Port $Port -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl -TimeoutSec $TimeoutSec -SkipPublic $SkipPublic -SkipTunnel $SkipTunnel

# 讀取 / 遞增連續失敗計數器
$prevFail = 0
if (Test-Path -LiteralPath $FailCountFile) {
    try {
        $prevFail = (Get-Content -LiteralPath $FailCountFile -Raw | ConvertFrom-Json).count -as [int]
    } catch { $prevFail = 0 }
}

if ($checkResult.cascade.http.ok -eq $false -or $checkResult.cascade.process.ok -eq $false) {
    $newFail = $prevFail + 1
    $failPayload = @{
        count       = $newFail
        lastCheck   = $checkResult.checkedAt
        lastOk      = $false
        reason      = if ($checkResult.cascade.http.ok -eq $false) { "http_failed" } else { "process_failed" }
    }
    $failPayload | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $FailCountFile -Encoding UTF8
    $checkResult | Add-Member -NotePropertyName "consecutiveFails" -NotePropertyValue $newFail -Force
    Write-Log "FAIL #$newFail recorded (reason: $($failPayload.reason))" "WARN"
} else {
    # 成功，歸零計數
    if ($prevFail -gt 0) {
        Write-Log "Recovered after $prevFail failure(s)" "OK"
    }
    $failPayload = @{ count = 0; lastCheck = $checkResult.checkedAt; lastOk = $true; reason = $null }
    $failPayload | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $FailCountFile -Encoding UTF8
    $checkResult | Add-Member -NotePropertyName "consecutiveFails" -NotePropertyValue 0 -Force
}

# 決定 overallOk 與告警閾值
$httpLevel   = $checkResult.cascade.http
$tunnelLevel = $checkResult.cascade.tunnel

if ($httpLevel.ok -eq $true) {
    $checkResult.overallOk = $true
} elseif ($httpLevel.ok -eq $false -and $httpLevel.detail -eq "skipped (process check failed)") {
    $checkResult.overallOk = $false
} else {
    $checkResult.overallOk = $false
}

$checkResult.shouldAlert = ($checkResult.consecutiveFails -ge 3)

# 寫入 JSON summary
$summaryDir = Split-Path -Path $SummaryJson -Parent
if (-not (Test-Path -LiteralPath $summaryDir)) {
    New-Item -ItemType Directory -Force -Path $summaryDir | Out-Null
}

# 最終 JSON 結構（乾淨版，移除重複欄位）
$pass = 0; $fail = 0; $skip = 0
# Iterate over actual dictionary keys (not PSObject.Properties which also exposes
# OrderedDictionary intrinsic members like Count/Keys/Values)
foreach ($key in $checkResult.cascade.Keys) {
    $entry = $checkResult.cascade[$key]
    if    ($entry.ok -eq $true)  { $pass++ }
    elseif ($entry.ok -eq $false) { $fail++ }
    else                         { $skip++ }
}

$finalJson = [ordered]@{
    generatedAt       = $checkResult.checkedAt
    host              = $checkResult.host
    port              = $checkResult.port
    overallOk         = $checkResult.overallOk
    shouldAlert       = $checkResult.shouldAlert
    consecutiveFails  = $checkResult.consecutiveFails
    alertThreshold    = 3
    cascade           = $checkResult.cascade
    counts            = @{ pass = $pass; fail = $fail; skip = $skip }
    failureCountFile = $FailCountFile
    checkScript       = $PSCommandPath
    runtimeRoot       = $RuntimeRoot
}

$finalJson | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $SummaryJson -Encoding UTF8

# ── Log 摘要輸出 ─────────────────────────────────────────────────────────────
if ($checkResult.overallOk) {
    Write-Log "Overall: PASS" "OK"
} elseif ($checkResult.shouldAlert) {
    Write-Log "Overall: ALERT (consecutiveFails=$($checkResult.consecutiveFails) >= 3)" "ERROR"
} else {
    Write-Log "Overall: FAIL (consecutiveFails=$($checkResult.consecutiveFails) < 3 — not yet alerting)" "WARN"
}

foreach ($prop in @("process", "port", "tcp", "http", "tunnel")) {
    $entry = $checkResult.cascade.$prop
    if ($null -eq $entry) { continue }
    $sym = switch ($entry.ok) {
        $true   { "✓" }
        $false  { "✗" }
        default { "○" }
    }
    $lvl = $entry.level
    $detail = $entry.detail
    Write-Log "  [$lvl] $sym $prop — $detail"
}

Write-Log "JSON written to: $SummaryJson"
Write-Log "Fail counter file: $FailCountFile (count=$($checkResult.consecutiveFails))"
Write-Log "=== MCP Health Check Finished ==="

exit $(if ($checkResult.overallOk) { 0 } else { 1 })
