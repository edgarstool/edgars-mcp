@echo off
chcp 65001 >nul
cd /d V:\projects\edgars-mcp
set "PYCORE=C:\Users\EdgarsTool\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe"
if exist "%PYCORE%" (
  start "edgars-mcp 控制台" "%PYCORE%" "V:\projects\edgars-mcp\scripts\edgars-mcp-console.py"
  exit /b 0
)
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
echo 找不到 pythonw，改用有黑窗的 python。
if exist "C:\Users\EdgarsTool\AppData\Local\Python\pythoncore-3.14-64\python.exe" (
  "C:\Users\EdgarsTool\AppData\Local\Python\pythoncore-3.14-64\python.exe" "V:\projects\edgars-mcp\scripts\edgars-mcp-console.py"
) else (
  py -3 "V:\projects\edgars-mcp\scripts\edgars-mcp-console.py"
)
if errorlevel 1 pause
