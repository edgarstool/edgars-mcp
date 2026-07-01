param(
    [string]$LocalBaseUrl = "http://127.0.0.1:8765",
    [string]$PublicMcpUrl = "https://mcp.edgars.tools/mcp",
    [int]$TimeoutSec = 10,
    [switch]$SkipPublic
)

$ErrorActionPreference = "Stop"

function Test-CommandAvailable {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-PortListening {
    param([int]$Port)

    $matches = netstat -ano | Select-String -Pattern ":$Port\s+.*LISTENING"
    return [bool]$matches
}

function Invoke-JsonProbe {
    param(
        [string]$Name,
        [string]$Uri,
        [string]$Method = "GET"
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -Method $Method -TimeoutSec $TimeoutSec
        $finalUri = $Uri
        if ($response.BaseResponse -and $response.BaseResponse.ResponseUri) {
            $finalUri = $response.BaseResponse.ResponseUri.AbsoluteUri
        }
        $detail = $null
        if ($finalUri -match "cloudflareaccess\.com") {
            $detail = "cloudflare_access_login"
        } elseif ([string]$response.Content -match "cloudflareaccess\.com|cf_access") {
            $detail = "cloudflare_access_login"
        }
        return [ordered]@{
            name = $Name
            ok = $true
            status = [int]$response.StatusCode
            uri = $Uri
            final_uri = $finalUri
            detail = $detail
        }
    } catch {
        $statusCode = $null
        $detail = $null
        if ($_.Exception.Response -and $_.Exception.Response.StatusCode) {
            $statusCode = [int]$_.Exception.Response.StatusCode
            try {
                $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
                $body = $reader.ReadToEnd()
                if ($body -match "DNS points to prohibited IP") {
                    $detail = "cloudflare_error_1000_dns_prohibited_ip"
                } elseif ($body -match "cloudflareaccess\.com|cf_access") {
                    $detail = "cloudflare_access_blocked"
                }
            } catch {
                $detail = $null
            }
        }
        return [ordered]@{
            name = $Name
            ok = $false
            status = $statusCode
            uri = $Uri
            error = $_.Exception.Message
            detail = $detail
        }
    }
}

$localHealthUrl = "$($LocalBaseUrl.TrimEnd('/'))/health"
$checks = @()
$checks += [ordered]@{
    name = "port_8765_listening"
    ok = Test-PortListening -Port 8765
    port = 8765
}
$checks += Invoke-JsonProbe -Name "local_health" -Uri $localHealthUrl
$checks += [ordered]@{
    name = "cloudflared_process"
    ok = [bool](Get-Process cloudflared -ErrorAction SilentlyContinue)
}
$checks += [ordered]@{
    name = "cloudflared_command"
    ok = Test-CommandAvailable -Name "cloudflared"
}
$checks += [ordered]@{
    name = "doppler_command"
    ok = Test-CommandAvailable -Name "doppler"
}

if (-not $SkipPublic) {
    $publicBaseUrl = ($PublicMcpUrl -replace "/mcp$", "")
    $publicHealth = Invoke-JsonProbe -Name "public_health" -Uri "$publicBaseUrl/health"
    if ($publicHealth.ok -and $publicHealth.detail -eq "cloudflare_access_login") {
        $publicHealth.note = "reachable_access_protected"
    }
    if (-not $publicHealth.ok -and $publicHealth.status -in @(302, 401, 403, 405)) {
        $publicHealth.ok = $true
        $publicHealth.note = "reachable_auth_required"
    }
    $checks += $publicHealth

    $publicMcp = Invoke-JsonProbe -Name "public_mcp_get" -Uri $PublicMcpUrl
    if ($publicMcp.ok -and $publicMcp.detail -eq "cloudflare_access_login") {
        $publicMcp.note = "reachable_access_protected"
    }
    if (-not $publicMcp.ok -and $publicMcp.status -in @(302, 401, 403, 405)) {
        $publicMcp.ok = $true
        $publicMcp.note = "reachable_auth_required"
    }
    $checks += $publicMcp
}

$ok = -not [bool](
    $checks | Where-Object {
        if ($_.ok) {
            return $false
        }
        return $_.detail -notin @("cloudflare_access_blocked", "cloudflare_access_login")
    }
)
$result = [ordered]@{
    ok = $ok
    local_base_url = $LocalBaseUrl
    public_mcp_url = if ($SkipPublic) { $null } else { $PublicMcpUrl }
    checked_at = (Get-Date).ToString("o")
    checks = $checks
}

$result | ConvertTo-Json -Depth 6
if (-not $ok) {
    exit 1
}
