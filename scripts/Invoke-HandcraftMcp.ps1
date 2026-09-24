param(
    [string]$McpUrl = "http://127.0.0.1:8765/mcp",
    [string]$BodyJson = '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}',
    [int]$TimeoutSec = 10
)

$ErrorActionPreference = "Stop"

function Get-HandcraftMcpToken {
    foreach ($name in @("EDGARS_API_TOKEN", "MCP_API_TOKEN", "HERMES_HANDCRAFT_MCP_TOKEN", "MCP_AUTH_TOKEN", "EDGARS_TOOLS_API_TOKEN")) {
        $value = [Environment]::GetEnvironmentVariable($name, "Process")
        if (-not $value) {
            $value = [Environment]::GetEnvironmentVariable($name, "User")
        }
        if (-not $value) {
            $value = [Environment]::GetEnvironmentVariable($name, "Machine")
        }
        if ($value -and $value.Trim()) {
            return $value.Trim()
        }
    }

    throw "No MCP token found in env. Set EDGARS_API_TOKEN or MCP_API_TOKEN in Process/User/Machine scope."
}

$token = Get-HandcraftMcpToken
$headers = @{
    "Content-Type" = "application/json"
    "Accept" = "application/json, text/event-stream"
    "Authorization" = "Bearer $token"
}

Invoke-RestMethod `
    -Uri $McpUrl `
    -Method Post `
    -Headers $headers `
    -Body $BodyJson `
    -TimeoutSec $TimeoutSec
