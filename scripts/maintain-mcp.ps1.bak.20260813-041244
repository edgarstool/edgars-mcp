<#
.SYNOPSIS
  handcraft MCP 維護腳本：依賴檢查、日誌輪替、健康修復、可選 smoke test。
  Maintenance for handcraft MCP: deps, log rotation, unhealthy restart, optional smoke test.

.DESCRIPTION
  預設為安全模式（不部署、不改 production DNS）。
  - 檢查 doppler / python / cloudflared
  - 輪替 handcraft-http 與 cache-trace 日誌
  - -RestartIfUnhealthy：check 失敗時呼叫 start-mcp.ps1
  - -SmokeTest：執行 test_server_http.py（較慢）
  - -PrepareDeploy：只輸出部署前檢查清單，不執行 wrangler deploy

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\maintain-mcp.ps1

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\maintain-mcp.ps1 -RestartIfUnhealthy -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [switch]$RestartIfUnhealthy,
    [switch]$SmokeTest,
    [switch]$PrepareDeploy,
    [switch]$SkipLogRotation,
    [switch]$SkipPublicCheck,
    [double]$LogMaxSizeMB = 16,
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Get-Help $PSCommandPath -Full
    exit 0
}

$modulePath = Join-Path $PSScriptRoot "Handcraft-McpCommon.psm1"
Import-Module $modulePath -Force

$config = Get-HandcraftConfig -LocalBaseUrl $LocalBaseUrl -PublicMcpUrl $PublicMcpUrl
$actions = @()
$issues = @()

function Add-Action {
    param([string]$Name, [bool]$Ok, [object]$Detail = $null)
    $script:actions += [ordered]@{ name = $Name; ok = $Ok; detail = $Detail }
    if (-not $Ok) { $script:issues += $Name }
}

# ── Runtime commands ─────────────────────────────────────────────────────────
foreach ($cmd in @("doppler", "cloudflared")) {
    Add-Action -Name "command_$cmd" -Ok (Test-CommandAvailable -Name $cmd)
}

$pythonOk = (Test-CommandAvailable -Name "py") -or (Test-CommandAvailable -Name "python")
Add-Action -Name "command_python" -Ok $pythonOk

if (Test-CommandAvailable -Name "doppler") {
    try {
        if ($PSCmdlet.ShouldProcess("doppler", "verify project/config")) {
            $null = & doppler configs --project $config.DopplerProject --json 2>$null | Out-Null
            Add-Action -Name "doppler_project" -Ok $true -Detail $config.DopplerProject
        } else {
            Add-Action -Name "doppler_project" -Ok $true -Detail "whatif"
        }
    } catch {
        Add-Action -Name "doppler_project" -Ok $false -Detail $_.Exception.Message
    }
}

# ── Log rotation ─────────────────────────────────────────────────────────────
if (-not $SkipLogRotation) {
    $logTargets = @(
        $config.HttpOutLog,
        $config.HttpErrLog,
        $config.CloudflaredOutLog,
        $config.CloudflaredErrLog,
        (Join-Path $config.RepoLogDir "cache-trace.jsonl")
    )

    $rotationResults = @()
    foreach ($logPath in $logTargets) {
        if ($logPath -like "*cache-trace.jsonl") {
            $rotateScript = Join-Path $PSScriptRoot "Rotate-CacheTrace.ps1"
            if ((Test-Path -LiteralPath $rotateScript) -and (Test-Path -LiteralPath $logPath)) {
                if ($PSCmdlet.ShouldProcess($logPath, "rotate cache trace")) {
                    $rotationResults += & powershell -NoProfile -ExecutionPolicy Bypass -File $rotateScript -LogPath $logPath -PassThru
                }
            }
            continue
        }

        if ($PSCmdlet.ShouldProcess($logPath, "rotate log")) {
            $rotationResults += Rotate-HandcraftLogFile -LogPath $logPath -MaxSizeMB $LogMaxSizeMB
        } elseif ($WhatIfPreference) {
            $rotationResults += Rotate-HandcraftLogFile -LogPath $logPath -MaxSizeMB $LogMaxSizeMB -WhatIf
        }
    }
    Add-Action -Name "log_rotation" -Ok $true -Detail $rotationResults
}

# ── Health check ─────────────────────────────────────────────────────────────
$checkScript = Join-Path $PSScriptRoot "check-mcp.ps1"
$checkArgs = @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $checkScript,
    "-LocalBaseUrl", $config.LocalBaseUrl,
    "-PublicMcpUrl", $config.PublicMcpUrl
)
if ($SkipPublicCheck) {
    $checkArgs += "-SkipPublic"
}

$checkExit = 0
if ($PSCmdlet.ShouldProcess("handcraft MCP", "health check")) {
    & powershell @checkArgs | Out-Null
    $checkExit = $LASTEXITCODE
}
Add-Action -Name "health_check" -Ok ($checkExit -eq 0) -Detail @{ exit_code = $checkExit }

if ($RestartIfUnhealthy -and $checkExit -ne 0) {
    $startScript = Join-Path $PSScriptRoot "start-mcp.ps1"
    if ($PSCmdlet.ShouldProcess("handcraft MCP", "restart via start-mcp.ps1")) {
        $startArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $startScript, "-LocalBaseUrl", $config.LocalBaseUrl, "-PublicMcpUrl", $config.PublicMcpUrl)
        if ($SkipPublicCheck) { $startArgs += "-LocalOnly" }
        & powershell @startArgs | Out-Null
        $restartExit = $LASTEXITCODE
        Add-Action -Name "restart_if_unhealthy" -Ok ($restartExit -eq 0) -Detail @{ exit_code = $restartExit }
    }
}

# ── Optional smoke test ──────────────────────────────────────────────────────
if ($SmokeTest) {
    $testFile = Join-Path $config.RepoRoot "test_server_http.py"
    if (-not (Test-Path -LiteralPath $testFile)) {
        Add-Action -Name "smoke_test" -Ok $false -Detail "missing test_server_http.py"
    } elseif ($PSCmdlet.ShouldProcess($testFile, "run unittest smoke test")) {
        $python = if (Test-CommandAvailable -Name "py") { "py" } else { "python" }
        Push-Location $config.RepoRoot
        try {
            if ($python -eq "py") {
                & py -3 -m unittest test_server_http.py 2>&1 | Out-Null
            } else {
                & python -m unittest test_server_http.py 2>&1 | Out-Null
            }
            Add-Action -Name "smoke_test" -Ok ($LASTEXITCODE -eq 0)
        } finally {
            Pop-Location
        }
    }
}

# ── Deploy prep (no prod deploy) ─────────────────────────────────────────────
if ($PrepareDeploy) {
    $deployChecklist = [ordered]@{
        note = "PrepareDeploy only prints checklist; no wrangler deploy executed."
        steps = @(
            "Confirm doppler secrets for handcraft-mcp / prd",
            "Run maintain-mcp.ps1 -SmokeTest",
            "Run check-mcp.ps1 (local + external)",
            "Manual: review Cloudflare tunnel DNS (mcp.edgars.tools) before any deploy",
            "Manual: wrangler deploy only after explicit approval"
        )
    }
    Add-Action -Name "prepare_deploy" -Ok $true -Detail $deployChecklist
}

$ok = ($issues.Count -eq 0)
$result = [ordered]@{
    ok = $ok
    action = "maintain"
    issues = $issues
    actions = $actions
    checked_at = (Get-Date).ToString("o")
}

$result | ConvertTo-Json -Depth 8
if (-not $ok) {
    exit 1
}
exit 0
