# 排程用自動修復：連續失敗達門檻才重啟 MCP；linear-orchestrator 掛了則啟動
# 由 Windows 工作排程器 MCP-AutoRecover 每 15 分鐘呼叫
param(
    [switch]$OrchestratorOnly
)

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$LogsDir     = Join-Path $RepoRoot 'logs'
$RuntimeRoot = 'G:\AI_WORK_512\run\mcp-handcraft'
$LogPath     = Join-Path $LogsDir ("patrol-recover-{0:yyyyMMdd}.log" -f (Get-Date))
$DotLog      = Join-Path $PSScriptRoot 'patrol-write-log.ps1'
$RestartScript = Join-Path $PSScriptRoot 'restart-mcp.ps1'
$CommonModule  = Join-Path $PSScriptRoot 'Handcraft-McpCommon.psm1'
$OrchStart     = 'G:\AI_WORK_512\repos\linear-orchestrator\scripts\Start-LinearOrchestrator.ps1'
$FailThreshold = 3

function Write-PatrolLog([string]$Message, [string]$Level = 'INFO') {
    & $DotLog -LogPath $LogPath -Message $Message -Level $Level
}

function Test-PortListening([int]$Port) {
    return [bool](netstat -ano 2>$null | Select-String ":$Port\s+.*LISTENING")
}

function Get-ConsecutiveFailCount {
    $failFile = Join-Path $RuntimeRoot 'consecutive-failures.json'
    if (-not (Test-Path -LiteralPath $failFile)) { return 0 }
    try {
        $j = Get-Content -LiteralPath $failFile -Raw | ConvertFrom-Json
        return [int]$j.count
    } catch {
        Write-PatrolLog "無法讀取 consecutive-failures.json: $($_.Exception.Message)" 'WARN'
        return 0
    }
}

function Test-ShouldRestartMcp {
    $count = Get-ConsecutiveFailCount
    if ($count -ge $FailThreshold) {
        Write-PatrolLog "連續失敗 $count 次（門檻 $FailThreshold）→ 將重啟 MCP" 'WARN'
        return $true
    }

    $summaryPath = Join-Path $RuntimeRoot 'healthcheck-summary.json'
    if (Test-Path -LiteralPath $summaryPath) {
        try {
            $s = Get-Content -LiteralPath $summaryPath -Raw | ConvertFrom-Json
            if ($s.shouldAlert -eq $true -and $s.overallOk -eq $false) {
                Write-PatrolLog 'healthcheck-summary 標記 shouldAlert → 將重啟 MCP' 'WARN'
                return $true
            }
        } catch { }
    }

    Write-PatrolLog "MCP 狀態尚可（連續失敗 $count / $FailThreshold）— 跳過 MCP 重啟"
    return $false
}

function Invoke-StartLinearOrchestratorIfDown {
    $orchHealthy = $false

    if (Test-Path -LiteralPath $CommonModule) {
        try {
            Import-Module $CommonModule -Force -ErrorAction Stop
            $orch = Test-HandcraftLinearOrchestratorHealthy
            $orchHealthy = [bool]$orch.ok
        } catch {
            Write-PatrolLog "Handcraft-McpCommon 檢查 orchestrator 失敗: $($_.Exception.Message)" 'WARN'
        }
    }

    if (-not $orchHealthy) {
        $orchHealthy = (Test-PortListening -Port 8645)
    }

    if ($orchHealthy) {
        Write-PatrolLog 'linear-orchestrator 已在跑（:8645）' 'OK'
        return
    }

    if (-not (Test-Path -LiteralPath $OrchStart)) {
        Write-PatrolLog "找不到 $OrchStart — 無法啟動 orchestrator" 'ERROR'
        return
    }

    Write-PatrolLog 'linear-orchestrator 未運行 → 啟動中…' 'WARN'
    try {
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $OrchStart 2>&1 | ForEach-Object {
            Write-PatrolLog $_.ToString()
        }
        Start-Sleep -Seconds 3
        if (Test-PortListening -Port 8645) {
            Write-PatrolLog 'linear-orchestrator 啟動成功' 'OK'
        } else {
            Write-PatrolLog 'linear-orchestrator 啟動後 :8645 仍無 LISTENING' 'ERROR'
        }
    } catch {
        Write-PatrolLog "啟動 orchestrator 失敗: $($_.Exception.Message)" 'ERROR'
    }
}

Write-PatrolLog '=== patrol-auto-recover 開始 ==='

if (-not $OrchestratorOnly -and (Test-ShouldRestartMcp)) {
    if (-not (Test-Path -LiteralPath $RestartScript)) {
        Write-PatrolLog "找不到 $RestartScript" 'ERROR'
    } else {
        Write-PatrolLog '執行 restart-mcp.ps1 …' 'WARN'
        try {
            & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $RestartScript 2>&1 | ForEach-Object {
                Write-PatrolLog $_.ToString()
            }
            Write-PatrolLog "restart-mcp 完成（exit=$LASTEXITCODE）"
        } catch {
            Write-PatrolLog "restart-mcp 失敗: $($_.Exception.Message)" 'ERROR'
        }
    }
}

Invoke-StartLinearOrchestratorIfDown
Write-PatrolLog '=== patrol-auto-recover 結束 ==='
