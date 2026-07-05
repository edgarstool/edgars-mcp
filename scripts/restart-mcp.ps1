<#
.SYNOPSIS
  MCP 服務重啟腳本（專門負責重啟，不做健康檢查）。
  檢查失敗由 check-mcp-health.ps1 負責；此腳本只執行「停 → 等 → 啟」流程。

.DESCRIPTION
  停止流程：
    1. 從 pid file 讀取 PID
    2. 發送 SIGTERM / Ctrl+C / Stop-Process（視環境）
    3. 等候最多 WaitSeconds 秒確認程序退出

  啟動流程：
    1. 寫入新 PID 到 pid file
    2. 啟動 server_http.py（或 via start-mcp.ps1）
    3. 等候 /health 回 2xx

  會自動偵測兩種部署模式：
    - 直接 Python：http://127.0.0.1:8765
    - Cloudflare Tunnel：需要 cloudflared

  前置條件：check-mcp-health.ps1 已執行並寫入 consecutive-failures.json

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart-mcp.ps1
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart-mcp.ps1 -WhatIf
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart-mcp.ps1 -ForceRestart
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$LocalBaseUrl  = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl  = "https://mcp.edgars.tools/mcp",
    [int]$Port             = 8765,
    [int]$WaitSeconds      = 20,
    [int]$StartupWaitSec   = 15,
    [string]$FailureCountPath = "",  # 空字串 = 自動路徑
    [switch]$ForceRestart,
    [switch]$SkipCloudflared,
    [switch]$Help
)

$ErrorActionPreference = "Continue"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

# ── 路徑推導 ─────────────────────────────────────────────────────────────────
$RepoRoot     = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$RuntimeRoot  = "G:\AI_WORK_512\run\mcp-handcraft"
$RepoLogDir   = Join-Path $RepoRoot "logs"
$FailCountFile = if ($FailureCountPath) { $FailureCountPath } else { Join-Path $RuntimeRoot "consecutive-failures.json" }
$HttpPidFile  = Join-Path $RuntimeRoot "handcraft-http.pid"
$CfdPidFile   = Join-Path $RuntimeRoot "cloudflared.pid"
$todayLog     = Join-Path $RepoLogDir ("restart-mcp-" + (Get-Date -Format "yyyyMMdd") + ".log")

Import-Module (Join-Path $PSScriptRoot "Handcraft-McpCommon.psm1") -Force

function Write-Log {
    param([Parameter(ValueFromPipeline)][string]$Msg, [string]$Level = "INFO")
    $ts = Get-Date -Format "HH:mm:ss"
    $line = "[$ts] [$Level] $Msg"
    switch ($Level) {
        "ERROR" { Write-Host $line -ForegroundColor Red }
        "WARN"  { Write-Host $line -ForegroundColor Yellow }
        "OK"    { Write-Host $line -ForegroundColor Green }
        default { Write-Host $line }
    }
    $dir = Split-Path -Parent $todayLog
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Add-Content -LiteralPath $todayLog -Value $line -Encoding UTF8
}

# ── PID File helpers ──────────────────────────────────────────────────────────
function Read-PidFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $c = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        return [int]$c.pid
    } catch { return $null }
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

function Write-PidFile {
    param([string]$Path, [int]$ProcessId, [string]$Kind)
    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    @{
        pid        = $ProcessId
        kind       = $Kind
        started_at = (Get-Date).ToString("o")
        updated_at = (Get-Date).ToString("o")
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $Path -Encoding UTF8
}

# ── 程序停止 helpers ─────────────────────────────────────────────────────────
function Stop-ProcessByPid {
    param([int]$ProcessId, [int]$WaitSec = 10)
    $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Log "PID $ProcessId already gone" "INFO"
        return $true
    }
    Write-Log "Stopping PID $ProcessId (name: $($proc.ProcessName))..."
    try {
        $proc.CloseMainWindow() | Out-Null
        Start-Sleep -Milliseconds 500
        if (-not (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)) {
            Write-Log "PID $ProcessId exited via graceful close" "OK"
            return $true
        }
    } catch { }

    try {
        Stop-Process -Id $ProcessId -Force -ErrorAction Stop
        Write-Log "SIGTERM sent to PID $ProcessId" "INFO"
    } catch {
        Write-Log "Failed to stop PID ${ProcessId}: $($_.Exception.Message)" "ERROR"
        return $false
    }

    $killed = $proc.WaitForExit($WaitSec * 1000)
    if (-not $killed) {
        Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
        Write-Log "Force-killed PID $ProcessId" "WARN"
    }
    return $true
}

# ── 停止雲端 tunnel 程序 ──────────────────────────────────────────────────────
function Stop-TunnelProcess {
    $cfdPid = Read-PidFile -Path $CfdPidFile
    if ($cfdPid) {
        Write-Log "Stopping cloudflared PID $cfdPid..."
        Stop-ProcessByPid -ProcessId $cfdPid -WaitSec 10
    }
    # 也殺沒有 pid file 的殭屍 cloudflared
    Get-Process cloudflared -ErrorAction SilentlyContinue | ForEach-Object {
        Write-Log "Cleaning up orphan cloudflared PID $($_.Id)..."
        Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}

# ── 啟動 server ──────────────────────────────────────────────────────────────
function Start-ServerProcess {
    param([int]$StartupWaitSec = 15)

    $serverScript = Join-Path $RepoRoot "server_http.py"
    if (-not (Test-Path -LiteralPath $serverScript)) {
        # fallback：找 startup stack script
        $alt = Join-Path $RepoRoot "scripts\Start-HandcraftStack.ps1"
        if (Test-Path -LiteralPath $alt) {
            Write-Log "Using startup stack: $alt" "INFO"
            $job = Start-Process powershell -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File",$alt -PassThru -WindowStyle Hidden
            Start-Sleep $StartupWaitSec
            if ($null -eq (Get-Process -Id $job.Id -ErrorAction SilentlyContinue)) {
                Write-Log "Fallback startup stack exited before health verification" "ERROR"
                return $null
            }
            $ownerPid = Get-NetstatPid -Port $Port
            if ($ownerPid) {
                Write-Log "Fallback startup stack brought port $Port online via PID $ownerPid" "OK"
                Write-PidFile -Path $HttpPidFile -ProcessId $ownerPid -Kind "handcraft-http"
                return $ownerPid
            }
            Write-Log "Fallback startup stack ran but no listener found on port $Port" "ERROR"
            return $null
        }
        Write-Log "server_http.py not found at $serverScript" "ERROR"
        return $false
    }

    # 對齊目前 repo 內可用啟動方式：優先 py -3，其次 python；若有 Doppler 則固定 handcraft-mcp/prd
    $dopplerCommand = Get-Command doppler -ErrorAction SilentlyContinue
    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    $pythonArgs = @("-3", $serverScript)
    if (-not $pythonCommand) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        $pythonArgs = @($serverScript)
    }

    if (-not $pythonCommand) {
        Write-Log "Neither 'py' nor 'python' is available on PATH" "ERROR"
        return $null
    }

    $outLog = Join-Path $RepoLogDir "handcraft-http.out.log"
    $errLog = Join-Path $RepoLogDir "handcraft-http.err.log"

    if ($dopplerCommand) {
        $args = @(
            "run",
            "--project", "handcraft-mcp",
            "--config", "prd",
            "--",
            $pythonCommand.Source
        ) + $pythonArgs
        Write-Log "Launching via Doppler (handcraft-mcp/prd): $($pythonCommand.Source) $($pythonArgs -join ' ')"
        $proc = Start-Process -FilePath $dopplerCommand.Source -ArgumentList $args `
            -WorkingDirectory $RepoRoot `
            -PassThru `
            -RedirectStandardOutput $outLog `
            -RedirectStandardError $errLog `
            -WindowStyle Hidden
    } else {
        Write-Log "Launching directly: $($pythonCommand.Source) $($pythonArgs -join ' ')"
        $proc = Start-Process -FilePath $pythonCommand.Source -ArgumentList $pythonArgs `
            -WorkingDirectory $RepoRoot `
            -PassThru `
            -RedirectStandardOutput $outLog `
            -RedirectStandardError $errLog `
            -WindowStyle Hidden
    }

    if ($proc) {
        Start-Sleep -Seconds 1
        if ($proc.HasExited) {
            Write-Log "Server process exited immediately with code $($proc.ExitCode). See $errLog" "ERROR"
            return $null
        }
        Write-Log "Server started, PID = $($proc.Id)" "OK"
        Write-PidFile -Path $HttpPidFile -ProcessId $proc.Id -Kind "handcraft-http"
        return $proc.Id
    } else {
        Write-Log "Failed to start server process" "ERROR"
        return $null
    }
}

# ── 啟動 Cloudflare Tunnel ───────────────────────────────────────────────────
function Start-TunnelProcess {
    if ($SkipCloudflared) {
        Write-Log "SkipCloudflared set — not starting tunnel" "INFO"
        return $true
    }

    $stoppedDeprecated = @(Stop-DeprecatedCloudflaredProcesses)
    if ($stoppedDeprecated.Count -gt 0) {
        Write-Log "Stopped deprecated cloudflared process(es): $($stoppedDeprecated -join ', ')" "WARN"
        Start-Sleep -Seconds 2
    }

    if (Test-HandcraftCloudflaredHealthy) {
        $existing = @(Get-Process cloudflared -ErrorAction SilentlyContinue)
        $pidList = if ($existing.Count -gt 0) { $existing.Id -join ', ' } else { "Cloudflared service" }
        Write-Log "Healthy cloudflared already running ($pidList) — skipping manual tunnel start" "INFO"
        return $true
    }

    $cloudflaredCommand = Get-Command cloudflared -ErrorAction SilentlyContinue
    if (-not $cloudflaredCommand) {
        Write-Log "cloudflared not found on PATH — skipping tunnel start" "WARN"
        return $false
    }

    $cfdOut = Join-Path $RepoLogDir "cloudflared.out.log"
    $cfdErr = Join-Path $RepoLogDir "cloudflared.err.log"

    Write-Log "Starting cloudflared tunnel: edgar-local-01-tunnel"
    $proc = Start-Process -FilePath $cloudflaredCommand.Source -ArgumentList @("tunnel", "run", "edgar-local-01-tunnel") `
        -WorkingDirectory $RepoRoot `
        -PassThru `
        -RedirectStandardOutput $cfdOut `
        -RedirectStandardError $cfdErr `
        -WindowStyle Hidden

    if ($proc) {
        Write-Log "cloudflared started, PID = $($proc.Id)" "OK"
        Write-PidFile -Path $CfdPidFile -ProcessId $proc.Id -Kind "cloudflared"
        return $true
    } else {
        Write-Log "Failed to start cloudflared" "ERROR"
        return $false
    }
}

# ── 健康等待 ──────────────────────────────────────────────────────────────────
function Wait-ForHealth {
    param([int]$Sec = 15, [int]$Port = 8765)
    $healthUri = "$($LocalBaseUrl.TrimEnd('/'))/health"
    Write-Log "Waiting up to $Sec seconds for /health to respond..."

    $ok = $false
    for ($i = 0; $i -lt $Sec; $i++) {
        Start-Sleep 1
        try {
            $r = Invoke-WebRequest -UseBasicParsing -Uri $healthUri -TimeoutSec 2 -DisableKeepAlive
            if ([int]$r.StatusCode -eq 200) {
                Write-Log "Health check passed after $($i+1) second(s)" "OK"
                return $true
            }
        } catch { }
        if ($i % 5 -eq 0 -and $i -gt 0) {
            Write-Log "Still waiting... ($($i+1)s)"
        }
    }
    Write-Log "Health check did not pass within $Sec seconds" "ERROR"
    return $false
}

# ══════════════════════════════════════════════════════════════════════════════
# 主程式
# ══════════════════════════════════════════════════════════════════════════════
Write-Log "=== MCP Restart Script Started ==="
Write-Log "RepoRoot: $RepoRoot / RuntimeRoot: $RuntimeRoot"
Write-Log "Port: $Port / LocalBaseUrl: $LocalBaseUrl"

if (-not $PSCmdlet.ShouldProcess("mcp-handcraft stack", "restart HTTP server and optional tunnel")) {
    Write-Log "WhatIf / ShouldProcess declined — no changes made" "WARN"
    exit 0
}

# ── 前置檢查：確認 failure count 達標 ─────────────────────────────────────────
if (-not $ForceRestart) {
    $failCount = 0
    if (Test-Path -LiteralPath $FailCountFile) {
        try {
            $failCount = [int]((Get-Content -LiteralPath $FailCountFile -Raw | ConvertFrom-Json).count)
        } catch { $failCount = 0 }
    }

    Write-Log "Failure count: $failCount / threshold: 3"
    if ($failCount -lt 3) {
        Write-Log "Threshold not met ($failCount < 3) — refusing to restart (use -ForceRestart to override)" "WARN"
        Write-Log "=== Restart Aborted ==="
        exit 0
    }
} else {
    Write-Log "-ForceRestart set — proceeding regardless of failure count" "WARN"
}

# ── Phase 1: 停止 ────────────────────────────────────────────────────────────
Write-Log "=== Phase 1: Stopping services ==="

$httpPid = Read-PidFile -Path $HttpPidFile
if ($httpPid) {
    $stopped = Stop-ProcessByPid -ProcessId $httpPid -WaitSec $WaitSeconds
    if (-not $stopped) {
        Write-Log "Failed to stop HTTP server gracefully — force stopping..." "WARN"
        Stop-Process -Id $httpPid -Force -ErrorAction SilentlyContinue
    }
} else {
    Write-Log "No HTTP PID file found — checking for orphan processes..."
    $orphan = Get-NetstatPid -Port $Port
    if ($orphan) {
        Write-Log "Found orphan process on port $Port (PID $orphan) — killing..."
        Stop-Process -Id $orphan -Force -ErrorAction SilentlyContinue
    }
}

if (-not $SkipCloudflared) {
    Stop-TunnelProcess
}

Write-Log "All services stopped" "OK"

# ── Phase 2: 等待散盡 ────────────────────────────────────────────────────────
Write-Log "Waiting ${WaitSeconds}s for ports to be released..."
Start-Sleep $WaitSeconds

# ── Phase 3: 啟動 ────────────────────────────────────────────────────────────
Write-Log "=== Phase 3: Starting services ==="

$serverPid = Start-ServerProcess -StartupWaitSec $StartupWaitSec
if (-not $serverPid) {
    Write-Log "Server failed to start — aborting restart" "ERROR"
    Write-Log "=== Restart FAILED ==="
    exit 1
}

# 等 health 確認
$healthOk = Wait-ForHealth -Sec $StartupWaitSec -Port $Port
if (-not $healthOk) {
    Write-Log "Health check failed after startup — server may be running but unhealthy" "ERROR"
    Write-Log "=== Restart PARTIAL (server up, health check failed) ==="
    # 不 exit 1，因為 server 起來了只是 health endpooint 還沒ready
    # 繼續嘗試 tunnel
}

# ── Phase 4: Tunnel ─────────────────────────────────────────────────────────
if (-not $SkipCloudflared) {
    Write-Log "=== Phase 4: Starting tunnel ==="
    Start-TunnelProcess
    # cloudflared 啟動需要額外幾秒
    Start-Sleep 5
    Write-Log "Tunnel started (if cloudflared config valid)" "OK"
}

# ── 寫入 restart 事件 ────────────────────────────────────────────────────────
$restartEvent = Join-Path $RuntimeRoot "restart-events.jsonl"
$event = @{
    timestamp    = (Get-Date).ToString("o")
    host         = $env:COMPUTERNAME
    httpPid      = $serverPid
    forced       = $ForceRestart
    healthOk     = $healthOk
    skipCloudflared = $SkipCloudflared
} | ConvertTo-Json -Compress
Add-Content -LiteralPath $restartEvent -Value $event -Encoding UTF8

Write-Log "Restart event logged to: $restartEvent"
Write-Log "=== Restart Complete ==="
exit 0
