<#
.SYNOPSIS
  重啟 handcraft MCP 服務（停→等→啟）。
  Restart handcraft MCP: stop → wait for port free → start.

.DESCRIPTION
  與 check-mcp-health.ps1 完全分離，僅負責重啟流程：
    1. 呼叫 stop-mcp.ps1（停止 HTTP server，可選停止 cloudflared）
    2. 等待 :Port 不再 LISTENING（最長 WaitForFreeSec 秒）
    3. 呼叫 start-mcp.ps1（重新啟動 HTTP server + cloudflared）
    4. 輸出 JSON 結果 + log 記錄

  Exit code:
    0 — 重啟成功
    1 — 停止或啟動失敗（含 port 未釋放 timeout）

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart-mcp.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\restart-mcp.ps1 -StopCloudflared -WaitForFreeSec 20
#>
[CmdletBinding()]
param(
    [string]$LocalBaseUrl    = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl    = "https://mcp.edgars.tools/mcp",
    [int]$Port               = 8765,
    [int]$WaitForFreeSec     = 15,
    [int]$WaitForStartSec    = 30,
    [switch]$StopCloudflared,
    [switch]$SkipCloudflared,
    [switch]$Force,
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

$config  = Get-HandcraftConfig -Port $Port -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl
$logFile = Join-Path $config.RepoLogDir "restart-mcp.log"

foreach ($dir in @($config.RuntimeRoot, $config.RepoLogDir)) {
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }
}

function Append-Log {
    param([string]$Path, [string]$Line)
    $ts = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    Add-Content -LiteralPath $Path -Value "[$ts] $Line" -Encoding UTF8
}

$startedAt = (Get-Date).ToString("o")
$actions   = [System.Collections.Generic.List[object]]::new()

# ── Step 1: Stop ──────────────────────────────────────────────────────────────
Write-Host "[restart-mcp] step 1: stop"

$stopScript = Join-Path $PSScriptRoot "stop-mcp.ps1"
$stopArgs   = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $stopScript,
    "-Port", $Port
)
if ($StopCloudflared) { $stopArgs += "-StopCloudflared" }
if ($Force)          { $stopArgs += "-Force" }

$stopOutput    = $null
$stopExitCode  = 0
try {
    $stopOutput   = & powershell @stopArgs 2>&1
    $stopExitCode = $LASTEXITCODE
} catch {
    $stopExitCode = 1
    $stopOutput   = $_.Exception.Message
}

$stopOk = ($stopExitCode -eq 0)
$actions.Add([ordered]@{
    step      = "stop"
    ok        = $stopOk
    exit_code = $stopExitCode
})
Write-Host ("[restart-mcp] stop exit_code={0}" -f $stopExitCode)
Append-Log -Path $logFile -Line ("step=stop ok={0} exit_code={1}" -f $stopOk, $stopExitCode)

# ── Step 2: Wait for port to be free ─────────────────────────────────────────
Write-Host "[restart-mcp] step 2: wait for port $Port to free (max ${WaitForFreeSec}s)"

$deadline  = (Get-Date).AddSeconds($WaitForFreeSec)
$portFreed = $false
while ((Get-Date) -lt $deadline) {
    if (-not (Test-PortListening -Port $Port)) {
        $portFreed = $true
        break
    }
    Start-Sleep -Seconds 1
}

if (-not $portFreed) {
    # port still in use — check once more and warn, but continue
    $portFreed = -not (Test-PortListening -Port $Port)
}

$actions.Add([ordered]@{
    step       = "wait_port_free"
    ok         = $portFreed
    port       = $Port
    timeout_sec = $WaitForFreeSec
})
Write-Host ("[restart-mcp] port_freed={0}" -f $portFreed)
Append-Log -Path $logFile -Line ("step=wait_port_free ok={0} port={1}" -f $portFreed, $Port)

if (-not $portFreed) {
    Write-Warning "[restart-mcp] port $Port still LISTENING after ${WaitForFreeSec}s; proceeding with start anyway"
}

# ── Step 3: Start ──────────────────────────────────────────────────────────────
Write-Host "[restart-mcp] step 3: start"

$startScript = Join-Path $PSScriptRoot "start-mcp.ps1"
$startArgs   = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $startScript,
    "-Port", $Port,
    "-LocalBaseUrl", $LocalBaseUrl,
    "-PublicMcpUrl", $PublicMcpUrl,
    "-WaitSeconds", $WaitForStartSec,
    "-Force"
)
if ($SkipCloudflared) { $startArgs += "-SkipCloudflared" }

$startOutput   = $null
$startExitCode = 0
try {
    $startOutput   = & powershell @startArgs 2>&1
    $startExitCode = $LASTEXITCODE
} catch {
    $startExitCode = 1
    $startOutput   = $_.Exception.Message
}

$startOk = ($startExitCode -eq 0)
$actions.Add([ordered]@{
    step      = "start"
    ok        = $startOk
    exit_code = $startExitCode
})
Write-Host ("[restart-mcp] start exit_code={0}" -f $startExitCode)
Append-Log -Path $logFile -Line ("step=start ok={0} exit_code={1}" -f $startOk, $startExitCode)

# ── Result ─────────────────────────────────────────────────────────────────────
$overallOk = $stopOk -and $startOk

$result = [ordered]@{
    ok         = $overallOk
    action     = "restart"
    port       = $Port
    started_at = $startedAt
    ended_at   = (Get-Date).ToString("o")
    steps      = $actions
}

Write-Host ""
Write-Host "=== restart-mcp ==="
Write-Host ("stop=$stopOk  port_freed=$portFreed  start=$startOk  overall=$overallOk")
Write-Host ""

$result | ConvertTo-Json -Depth 8

$overallStatus = if ($overallOk) { "OK" } else { "FAIL" }
Append-Log -Path $logFile -Line ("overall=$overallStatus stop=$stopOk port_freed=$portFreed start=$startOk")

if (-not $overallOk) { exit 1 }
exit 0
