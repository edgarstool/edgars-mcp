@echo off
chcp 65001 >nul
cd /d V:\projects\edgars-mcp
where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "edgars-mcp 控制台" pyw -3 "V:\projects\edgars-mcp\scripts\edgars-mcp-console.py"
  exit /b 0
)
where pythonw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "edgars-mcp 控制台" pythonw "V:\projects\edgars-mcp\scripts\edgars-mcp-console.py"
  exit /b 0
)
echo 找不到 pyw / pythonw，改用有黑窗的 py。
py -3 "V:\projects\edgars-mcp\scripts\edgars-mcp-console.py"
if errorlevel 1 pause
