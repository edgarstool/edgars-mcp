@echo off
setlocal
:: Native Windows HTTP launch: no Docker, no 1Password Connect, no op run.
:: Secrets / Descope flags come from User + Machine environment variables.
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

if not defined MCP_DESCOPE_ENABLED set "MCP_DESCOPE_ENABLED=true"
if not defined MCP_DESCOPE_PROJECT_ID set "MCP_DESCOPE_PROJECT_ID=P3IHk9JHELKS5KT5EWawFro5aPhY"
if not defined MCP_DESCOPE_RESOURCE_SERVER_ID set "MCP_DESCOPE_RESOURCE_SERVER_ID=RS3IPp7u1MjAlO6wHaafMEw6bgu4C"
if not defined MCP_DESCOPE_AUDIENCE set "MCP_DESCOPE_AUDIENCE=https://mcp.edgars.tools/mcp"
if not defined MCP_AUTH_SERVER set "MCP_AUTH_SERVER=https://auth.edgars.tools"
if not defined MCP_BASE_URL set "MCP_BASE_URL=https://mcp.edgars.tools"
if not defined MCP_BIND_HOST set "MCP_BIND_HOST=0.0.0.0"
set "MCP_WRAP_OP_CONNECT=0"

set "PYEXE=C:\Users\EdgarsTool\AppData\Local\Python\pythoncore-3.14-64\python.exe"
if exist "%PYEXE%" (
    "%PYEXE%" "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
    "%PYEXE%" "%~dp0server_http.py" >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
    goto :eof
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
    py -3 "%~dp0server_http.py" >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
) else (
    python "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
    python "%~dp0server_http.py" >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
)
