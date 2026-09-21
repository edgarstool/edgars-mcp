# Handcraft-McpCommon.psm1
# Shared helpers for mcp-handcraft ops scripts (start / check / maintain / stop).
# 共用設定與探測函式，供 start-mcp / check-mcp / maintain-mcp / stop-mcp 使用。

Set-StrictMode -Version Latest

$Script:HandcraftDefaults = [ordered]@{
    RepoRoot          = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
    Port              = 8765
    LocalBaseUrl      = "http://127.0.0.1:8765"
    PublicMcpUrl      = "https://mcp.edgars.tools/mcp"
    CloudflaredConfig = Join-Path $env:USERPROFILE ".cloudflared\config.yml"
    RuntimeRoot       = "G:\AI_WORK_512\run\mcp-handcraft"
    RepoLogDir        = (Join-Path (Resolve-Path (Join-Path $PSScriptRoot "..")).Path "logs")
    HttpPidFile       = "G:\AI_WORK_512\run\mcp-handcraft\handcraft-http.pid"
    CloudflaredPidFile = "G:\AI_WORK_512\run\mcp-handcraft\cloudflared.pid"
    WaitSeconds       = 30
}

function Import-HandcraftWindowsEnvironment {
    foreach ($target in @('Machine', 'User')) {
        $vars = [Environment]::GetEnvironmentVariables($target)
        foreach ($name in $vars.Keys) {
            if ([string]$name -eq 'Path') { continue }
            [Environment]::SetEnvironmentVariable([string]$name, [string]$vars[$name], 'Process')
        }
    }
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machinePath;$userPath"
}

function Get-HandcraftConfig {
    [CmdletBinding()]
    param(
        [int]$Port = $Script:HandcraftDefaults.Port,
        [string]$LocalBaseUrl,
        [string]$PublicMcpUrl,
        [string]$RuntimeRoot,
        [string]$RepoRoot
    )

    $root = if ($RepoRoot) { $RepoRoot } else { $Script:HandcraftDefaults.RepoRoot }
    $runtime = if ($RuntimeRoot) { $RuntimeRoot } else { $Script:HandcraftDefaults.RuntimeRoot }
    $base = if ($LocalBaseUrl) { $LocalBaseUrl.TrimEnd('/') } else { "http://127.0.0.1:$Port" }

    return [pscustomobject]@{
        RepoRoot           = $root
        ServerPath         = Join-Path $root "server_http.py"
        Port               = $Port
        LocalBaseUrl       = $base
        LocalHealthUrl     = "$base/health"
        LocalMcpUrl        = "$base/mcp"
        PublicMcpUrl       = if ($PublicMcpUrl) { $PublicMcpUrl } else { $Script:HandcraftDefaults.PublicMcpUrl }
        CloudflaredConfig  = $Script:HandcraftDefaults.CloudflaredConfig
        RuntimeRoot        = $runtime
        RepoLogDir         = Join-Path $root "logs"
        HttpPidFile        = Join-Path $runtime "handcraft-http.pid"
        CloudflaredPidFile = Join-Path $runtime "cloudflared.pid"
        HttpOutLog         = Join-Path $root "logs\handcraft-http.out.log"
        HttpErrLog         = Join-Path $root "logs\handcraft-http.err.log"
        CloudflaredOutLog  = Join-Path $root "logs\cloudflared.out.log"
        CloudflaredErrLog  = Join-Path $root "logs\cloudflared.err.log"
        WaitSeconds        = $Script:HandcraftDefaults.WaitSeconds
    }
}

function Write-HandcraftPidFile {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][int]$ProcessId,
        [string]$Kind = "handcraft-http",
        [string]$StartedAt = (Get-Date).ToString("o")
    )

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    @{
        pid        = $ProcessId
        kind       = $Kind
        started_at = $StartedAt
        updated_at = (Get-Date).ToString("o")
    } | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Read-HandcraftPidFile {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    try {
        $payload = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
        if ($null -ne $payload.pid) {
            return [int]$payload.pid
        }
    } catch {
        return $null
    }

    return $null
}

function Test-CommandAvailable {
    param([Parameter(Mandatory)][string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-PortListening {
    param([Parameter(Mandatory)][int]$Port)
    $matches = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING"
    return [bool]$matches
}

function Get-PortOwnerPid {
    param([Parameter(Mandatory)][int]$Port)

    $line = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING" | Select-Object -First 1
    if (-not $line) {
        return $null
    }

    $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
    if ($parts.Count -lt 1) {
        return $null
    }

    $pidText = $parts[-1]
    if ($pidText -match '^\d+$') {
        return [int]$pidText
    }

    return $null
}

function Test-ProcessAlive {
    param([Parameter(Mandatory)][int]$ProcessId)
    return [bool](Get-Process -Id $ProcessId -ErrorAction SilentlyContinue)
}

function Test-HandcraftLocalHealth {
    param(
        [Parameter(Mandatory)][string]$HealthUrl,
        [int]$TimeoutSec = 5
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec $TimeoutSec
        return [int]$response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-HandcraftHealth {
    param(
        [Parameter(Mandatory)][string]$HealthUrl,
        [int]$WaitSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($WaitSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-HandcraftLocalHealth -HealthUrl $HealthUrl) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return $false
}

function Get-PythonLaunchSpec {
    param([Parameter(Mandatory)][string]$ServerPath)

    $pythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return @{
            Executable = $pythonCommand.Source
            Arguments  = @("-3", $ServerPath)
        }
    }

    $pythonCommand = Get-Command python -ErrorAction Stop
    return @{
        Executable = $pythonCommand.Source
        Arguments  = @($ServerPath)
    }
}

function Start-HandcraftHttpServer {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Config,
        [switch]$Force,
        [hashtable]$ExtraEnv
    )

    if (-not $Force -and (Test-HandcraftLocalHealth -HealthUrl $Config.LocalHealthUrl)) {
        $ownerPid = Get-PortOwnerPid -Port $Config.Port
        if ($ownerPid) {
            Write-HandcraftPidFile -Path $Config.HttpPidFile -ProcessId $ownerPid
        }
        return [pscustomobject]@{
            started   = $false
            already_running = $true
            pid       = $ownerPid
            health_url = $Config.LocalHealthUrl
        }
    }

    if ($Force) {
        $ownerPid = Get-PortOwnerPid -Port $Config.Port
        if ($ownerPid) {
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
            $deadline = (Get-Date).AddSeconds(12)
            do {
                Start-Sleep -Milliseconds 400
            } while ((Get-PortOwnerPid -Port $Config.Port) -and ((Get-Date) -lt $deadline))
        }
        Remove-Item -LiteralPath $Config.HttpPidFile -Force -ErrorAction SilentlyContinue
    }

    if (-not (Test-Path -LiteralPath $Config.ServerPath)) {
        throw "server_http.py not found: $($Config.ServerPath)"
    }

    Import-HandcraftWindowsEnvironment

    # Ensure Descope auth defaults if User/Machine unset (public ids only).
    $descopeDefaults = @{
        MCP_DESCOPE_ENABLED            = "true"
        MCP_DESCOPE_PROJECT_ID         = "P3IHk9JHELKS5KT5EWawFro5aPhY"
        MCP_DESCOPE_RESOURCE_SERVER_ID = "RS3IPp7u1MjAlO6wHaafMEw6bgu4C"
        MCP_DESCOPE_AUDIENCE           = "https://mcp.edgars.tools/mcp"
        MCP_AUTH_SERVER                = "https://auth.edgars.tools"
        MCP_BASE_URL                   = "https://mcp.edgars.tools"
        MCP_BIND_HOST                  = "0.0.0.0"
    }
    foreach ($key in $descopeDefaults.Keys) {
        if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($key, 'Process'))) {
            Set-Item -Path "Env:$key" -Value $descopeDefaults[$key]
        }
    }
    if ([string]::IsNullOrWhiteSpace($env:MCP_API_TOKEN)) {
        throw "MCP_API_TOKEN is missing after loading Machine/User environment."
    }

    New-Item -ItemType Directory -Force -Path $Config.RepoLogDir | Out-Null
    New-Item -ItemType Directory -Force -Path $Config.RuntimeRoot | Out-Null

    $python = Get-PythonLaunchSpec -ServerPath $Config.ServerPath

    # Native Windows launcher: inherit Machine/User environment and only write
    # non-secret wrap flags into the .cmd. No Docker / 1Password / op run.
    $launcherPath = Join-Path $Config.RuntimeRoot "handcraft-native-launch.cmd"
    $quoteArg = {
        param([string]$Value)
        if ($null -eq $Value) { return '""' }
        return '"' + ($Value -replace '"', '""') + '"'
    }
    $pyQuoted = & $quoteArg $python.Executable
    $pyArgsQuoted = (@($python.Arguments) | ForEach-Object { & $quoteArg $_ }) -join " "
    $cmdLines = @(
        "@echo off",
        "rem Native launch: secrets inherit from parent process env; wrap flags below."
    )
    if ($null -eq $ExtraEnv) { $ExtraEnv = @{} }
    # Never persist OP Connect wrap on this path.
    $ExtraEnv["MCP_WRAP_OP_CONNECT"] = "0"
    foreach ($key in @($ExtraEnv.Keys | Sort-Object)) {
        $safeKey = [string]$key
        if ($safeKey -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
        $safeVal = ([string]$ExtraEnv[$key]) -replace "[\r\n]", ""
        Set-Item -Path "Env:$safeKey" -Value $safeVal
        if ($safeKey -match '(TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL)') { continue }
        $cmdLines += "set $safeKey=$safeVal"
    }
    # Also stamp non-secret Descope flags into launcher for visibility.
    foreach ($key in @($descopeDefaults.Keys | Sort-Object)) {
        $val = [Environment]::GetEnvironmentVariable($key, 'Process')
        if (-not [string]::IsNullOrWhiteSpace($val)) {
            $cmdLines += ("set {0}={1}" -f $key, ($val -replace "[\r\n]", ""))
        }
    }
    $cmdLines += "$pyQuoted $pyArgsQuoted"
    Set-Content -LiteralPath $launcherPath -Value ($cmdLines -join "`r`n") -Encoding ASCII

    # Start python directly so Machine/User secrets in this process are inherited.
    $process = Start-Process `
        -FilePath $python.Executable `
        -ArgumentList $python.Arguments `
        -WorkingDirectory $Config.RepoRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $Config.HttpOutLog `
        -RedirectStandardError $Config.HttpErrLog

    if (-not (Wait-HandcraftHealth -HealthUrl $Config.LocalHealthUrl -WaitSeconds $Config.WaitSeconds)) {
        throw "Timed out waiting for $($Config.LocalHealthUrl). See $($Config.HttpErrLog)"
    }

    $ownerPid = Get-PortOwnerPid -Port $Config.Port
    if (-not $ownerPid) {
        $ownerPid = $process.Id
    }

    Write-HandcraftPidFile -Path $Config.HttpPidFile -ProcessId $ownerPid

    return [pscustomobject]@{
        started         = $true
        already_running = $false
        pid             = $ownerPid
        launcher_pid    = $process.Id
        health_url      = $Config.LocalHealthUrl
        launcher        = $launcherPath
        mode            = "native"
    }
}

function Start-HandcraftCloudflared {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]$Config
    )

    $existing = Get-Process cloudflared -ErrorAction SilentlyContinue
    if ($existing) {
        $pidValue = @($existing | Select-Object -First 1)[0].Id
        Write-HandcraftPidFile -Path $Config.CloudflaredPidFile -ProcessId $pidValue -Kind "cloudflared"
        return [pscustomobject]@{
            started = $false
            already_running = $true
            pid = $pidValue
        }
    }

    if (-not (Test-Path -LiteralPath $Config.CloudflaredConfig)) {
        throw "Cloudflared config not found: $($Config.CloudflaredConfig)"
    }

    $cloudflared = Get-Command cloudflared -ErrorAction Stop
    $process = Start-Process `
        -FilePath $cloudflared.Source `
        -ArgumentList @("tunnel", "--config", $Config.CloudflaredConfig, "run") `
        -WorkingDirectory $Config.RepoRoot `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $Config.CloudflaredOutLog `
        -RedirectStandardError $Config.CloudflaredErrLog

    Write-HandcraftPidFile -Path $Config.CloudflaredPidFile -ProcessId $process.Id -Kind "cloudflared"

    return [pscustomobject]@{
        started = $true
        already_running = $false
        pid = $process.Id
    }
}

function Stop-HandcraftByPidFile {
    param(
        [Parameter(Mandatory)][string]$PidFile,
        [switch]$Force
    )

    $pidValue = Read-HandcraftPidFile -Path $PidFile
    if (-not $pidValue) {
        return [pscustomobject]@{ stopped = $false; reason = "pid_file_missing" }
    }

    if (-not (Test-ProcessAlive -ProcessId $pidValue)) {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        return [pscustomobject]@{ stopped = $false; reason = "process_not_running"; pid = $pidValue }
    }

    $stopArgs = @{ Id = $pidValue }
    if ($Force) { $stopArgs.Force = $true }
    Stop-Process @stopArgs -ErrorAction Stop
    Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    return [pscustomobject]@{ stopped = $true; pid = $pidValue }
}

function Invoke-HandcraftHttpProbe {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Uri,
        [string]$Method = "GET",
        [int]$TimeoutSec = 10
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -Method $Method -TimeoutSec $TimeoutSec
        $finalUri = $Uri
        if ($response.BaseResponse -and $response.BaseResponse.ResponseUri) {
            $finalUri = $response.BaseResponse.ResponseUri.AbsoluteUri
        }
        $detail = $null
        $note = $null
        $content = ""
        try {
            $content = [string]$response.Content
        } catch {
            $content = ""
        }
        if ($finalUri -match "cloudflareaccess\.com" -or $content -match "cloudflareaccess\.com|cf_access") {
            $detail = "cloudflare_access_login"
            $note = "reachable_access_login"
        }
        return [ordered]@{
            name      = $Name
            scope     = if ($Uri -match '^https?://127\.0\.0\.1|^https?://localhost') { "local" } else { "external" }
            ok        = $true
            status    = [int]$response.StatusCode
            uri       = $Uri
            final_uri = $finalUri
            detail    = $detail
            note      = $note
        }
    } catch {
        $statusCode = $null
        $detail = $null
        $finalUri = $Uri
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
            try {
                if ($_.Exception.Response.ResponseUri) {
                    $finalUri = $_.Exception.Response.ResponseUri.AbsoluteUri
                }
            } catch {
                $finalUri = $Uri
            }
        }
        return [ordered]@{
            name      = $Name
            scope     = if ($Uri -match '^https?://127\.0\.0\.1|^https?://localhost') { "local" } else { "external" }
            ok        = $false
            status    = $statusCode
            uri       = $Uri
            final_uri = $finalUri
            error     = $_.Exception.Message
            detail    = $detail
        }
    }
}

function Invoke-HandcraftLocalMcpHandshake {
    param(
        [Parameter(Mandatory)][string]$McpUrl,
        [int]$TimeoutSec = 15,
        [string]$RepoRoot = $Script:HandcraftDefaults.RepoRoot
    )

    try {
        $token = [Environment]::GetEnvironmentVariable("MCP_API_TOKEN", "Process")
        if ([string]::IsNullOrWhiteSpace($token)) {
            $token = [Environment]::GetEnvironmentVariable("MCP_API_TOKEN", "User")
        }
        if ([string]::IsNullOrWhiteSpace($token)) {
            $token = [Environment]::GetEnvironmentVariable("MCP_API_TOKEN", "Machine")
        }
        if ([string]::IsNullOrWhiteSpace($token)) {
            throw "MCP_API_TOKEN not available in Windows Process/User/Machine environment"
        }

        $headers = @{
            "Content-Type"  = "application/json"
            "Accept"        = "application/json, text/event-stream"
            "Authorization" = "Bearer $($token.Trim())"
        }
        $body = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
        $response = Invoke-RestMethod -Uri $McpUrl -Method Post -Headers $headers -Body $body -TimeoutSec $TimeoutSec
        $toolCount = $null
        if ($response -and $response.result -and $response.result.tools) {
            $toolCount = @($response.result.tools).Count
        }
        return [ordered]@{
            name = "local_mcp_handshake"; scope = "local"; ok = $true; uri = $McpUrl; tool_count = $toolCount
        }
    } catch {
        return [ordered]@{
            name = "local_mcp_handshake"; scope = "local"; ok = $false; uri = $McpUrl; error = $_.Exception.Message
        }
    }
}

function Rotate-HandcraftLogFile {
    param(
        [Parameter(Mandatory)][string]$LogPath,
        [double]$MaxSizeMB = 16,
        [int]$RetainRotated = 5,
        [switch]$WhatIf
    )

    $result = [ordered]@{
        log_path = $LogPath
        rotated  = $false
        reason   = "ok"
    }

    if (-not (Test-Path -LiteralPath $LogPath -PathType Leaf)) {
        $result.reason = "missing"
        return [pscustomobject]$result
    }

    $item = Get-Item -LiteralPath $LogPath
    if ($item.Length -le ($MaxSizeMB * 1MB)) {
        $result.reason = "under_threshold"
        return [pscustomobject]$result
    }

    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $rotatedPath = "$LogPath.$stamp.bak"
    if ($WhatIf) {
        $result.reason = "would_rotate"
        $result.rotated_path = $rotatedPath
        return [pscustomobject]$result
    }

    Move-Item -LiteralPath $LogPath -Destination $rotatedPath -Force
    New-Item -ItemType File -Path $LogPath -Force | Out-Null
    $result.rotated = $true
    $result.rotated_path = $rotatedPath

    $pattern = "$([System.IO.Path]::GetFileName($LogPath)).*.bak"
    $old = Get-ChildItem -LiteralPath (Split-Path -Parent $LogPath) -Filter $pattern |
        Sort-Object LastWriteTime -Descending |
        Select-Object -Skip $RetainRotated
    foreach ($entry in $old) {
        Remove-Item -LiteralPath $entry.FullName -Force -ErrorAction SilentlyContinue
    }

    return [pscustomobject]$result
}

Export-ModuleMember -Function @(
    'Import-HandcraftWindowsEnvironment',
    'Get-HandcraftConfig',
    'Write-HandcraftPidFile',
    'Read-HandcraftPidFile',
    'Test-CommandAvailable',
    'Test-PortListening',
    'Get-PortOwnerPid',
    'Test-ProcessAlive',
    'Test-HandcraftLocalHealth',
    'Wait-HandcraftHealth',
    'Get-PythonLaunchSpec',
    'Start-HandcraftHttpServer',
    'Start-HandcraftCloudflared',
    'Stop-HandcraftByPidFile',
    'Invoke-HandcraftHttpProbe',
    'Invoke-HandcraftLocalMcpHandshake',
    'Rotate-HandcraftLogFile'
)
