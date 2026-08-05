$ErrorActionPreference = 'Stop'
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*edgars_mcp.http_server*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

