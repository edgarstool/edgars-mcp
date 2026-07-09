# Manual smoke test for browser_visible_* tools against local MCP HTTP.
# Usage:
#   cd V:\projects\edgars-mcp
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-visible-browser.ps1

$ErrorActionPreference = "Stop"
Set-Location "V:\projects\edgars-mcp"

function Invoke-McpTool {
    param(
        [string]$Name,
        [hashtable]$Arguments = @{}
    )

    $payload = @{
        jsonrpc = "2.0"
        id      = 1
        method  = "tools/call"
        params  = @{
            name      = $Name
            arguments = $Arguments
        }
    } | ConvertTo-Json -Depth 6 -Compress

    $headers = @{
        "Content-Type"              = "application/json"
        "Accept"                    = "application/json"
        "X-Handcraft-Client-Mode"   = "stdio-local"
    }

    $token = $env:MCP_API_TOKEN
    if (-not $token) {
        $token = doppler secrets get MCP_API_TOKEN --project handcraft-mcp --config prd --plain 2>$null
    }
    if ($token) {
        $headers["Authorization"] = "Bearer $token"
    }

    $response = Invoke-RestMethod -Uri "http://127.0.0.1:8765/mcp" -Method Post -Headers $headers -Body $payload
    return $response.result.content[0].text
}

Write-Host "Opening visible browser..."
Write-Host (Invoke-McpTool -Name "browser_visible_open" -Arguments @{ url = "https://example.com"; slow_mo = 500 })
Start-Sleep -Seconds 2
Write-Host "Screenshot..."
Write-Host (Invoke-McpTool -Name "browser_visible_screenshot" -Arguments @{})
Start-Sleep -Seconds 1
Write-Host "Closing..."
Write-Host (Invoke-McpTool -Name "browser_visible_close" -Arguments @{})
