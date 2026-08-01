$ErrorActionPreference = 'Stop'
$BaseUrl = if ($env:EDGARS_MCP_CHECK_URL) { $env:EDGARS_MCP_CHECK_URL } else { 'http://127.0.0.1:8765' }
if (-not $env:MCP_API_TOKEN) { throw 'MCP_API_TOKEN is missing; run this check through op run.' }
$headers = @{ Authorization = "Bearer $env:MCP_API_TOKEN" }
$body = @{ jsonrpc = '2.0'; id = 1; method = 'tools/list'; params = @{} } | ConvertTo-Json -Compress
$health = Invoke-RestMethod "$BaseUrl/health"
$response = Invoke-RestMethod "$BaseUrl/mcp" -Method Post -Headers $headers -ContentType 'application/json' -Body $body
if (-not $health.ok -or $response.result.tools.Count -ne 78) { throw 'Health or tool contract check failed.' }
Write-Host 'PASS: health and 78 tools'

