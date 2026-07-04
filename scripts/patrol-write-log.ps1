# 巡邏腳本共用：寫入帶時間戳的日誌列
param(
    [Parameter(Mandatory)][string]$LogPath,
    [Parameter(Mandatory)][string]$Message,
    [ValidateSet('INFO', 'WARN', 'ERROR', 'OK')]
    [string]$Level = 'INFO'
)

$line = "[{0}] [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
$dir = Split-Path -Parent $LogPath
if ($dir -and -not (Test-Path -LiteralPath $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}
Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
