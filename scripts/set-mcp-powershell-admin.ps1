# 把登入排程 edgars-mcp-http 改成「以最高權限執行」。
# 這個排程的動作就是 PowerShell，MCP 以及它叫起來的 PowerShell 會跟著變成系統管理員。
# 必須在已提升的 PowerShell 裡跑。正式 tunnel 不會被關掉。
$ErrorActionPreference = "Stop"

$taskName = "edgars-mcp-http"
$repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$log = Join-Path "G:\AI_WORK_512\tmp" "mcp-powershell-admin.txt"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null

function Write-Log([string]$Message) {
    Add-Content -LiteralPath $log -Value ("[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message)
}

Set-Content -LiteralPath $log -Value "" -Encoding UTF8

$xml = [string](Export-ScheduledTask -TaskName $taskName)
if ($xml -match "<RunLevel>") {
    $xml = $xml -replace "<RunLevel>[^<]+</RunLevel>", "<RunLevel>HighestAvailable</RunLevel>"
} else {
    $xml = $xml -replace "(<LogonType>InteractiveToken</LogonType>)", "`$1`r`n      <RunLevel>HighestAvailable</RunLevel>"
}
Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
$level = [string](Get-ScheduledTask -TaskName $taskName).Principal.RunLevel
Write-Log "RunLevel=$level"
if ($level -ne "Highest") {
    throw "排程仍是 $level"
}

& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $repo "scripts\stop-mcp.ps1") -Force
Start-ScheduledTask -TaskName $taskName
Write-Log "restart-requested"

$deadline = (Get-Date).AddSeconds(45)
$healthy = $false
do {
    Start-Sleep -Seconds 2
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8765/health" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $healthy = $true }
    } catch {}
} while (-not $healthy -and (Get-Date) -lt $deadline)
Write-Log ("health=" + $(if ($healthy) { "200" } else { "down" }))

$pidFile = "G:\AI_WORK_512\run\mcp-handcraft\handcraft-http.pid"
if (Test-Path -LiteralPath $pidFile) {
    $procId = [int](Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json).pid
    Write-Log "pid=$procId"
    if (-not ("ProcElev" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class ProcElev {
  [DllImport("kernel32.dll")] public static extern IntPtr OpenProcess(uint a, bool b, int pid);
  [DllImport("advapi32.dll", SetLastError=true)] public static extern bool OpenProcessToken(IntPtr h, uint access, out IntPtr token);
  [DllImport("advapi32.dll", SetLastError=true)] public static extern bool GetTokenInformation(IntPtr token, int cls, out int info, int len, out int ret);
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr h);
  public static bool IsElevated(int pid) {
    IntPtr p = OpenProcess(0x1000, false, pid);
    if (p == IntPtr.Zero) return false;
    IntPtr tok;
    if (!OpenProcessToken(p, 0x0008, out tok)) { CloseHandle(p); return false; }
    int elev; int ret;
    bool ok = GetTokenInformation(tok, 20, out elev, 4, out ret);
    CloseHandle(tok); CloseHandle(p);
    return ok && elev != 0;
  }
}
"@
    }
    $elevated = [ProcElev]::IsElevated($procId)
    Write-Log ("elevated=" + $elevated)
}

Write-Log "done"
