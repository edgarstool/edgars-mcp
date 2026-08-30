@echo off
setlocal
:: FastAPI/uvicorn startup script for MCP Server (Phase 2.3)
:: Replaces run_http.cmd for production use.
:: Fallback: run_http.cmd still works with the old ThreadingHTTPServer.

:: Headless secrets: local Connect on 8877. Deleted SA token in the parent env
:: would 403 if Connect host is missing; Connect vars take precedence when both set.
set "OP_CONNECT_HOST=http://127.0.0.1:8877"
set "OP_SERVICE_ACCOUNT_TOKEN="
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"

:: Rotate logs
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
) else (
    python "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
)

:: Start uvicorn with FastAPI app
:: Uses port from MCP_PORT env var (default 8765)
:: Single worker to maintain compatibility with in-memory state
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    C:\Users\EdgarsTool\bin\op.exe run --env-file "%~dp0.env.op" -- py -3 -m uvicorn server_fastapi:app --host 0.0.0.0 --port 8765 --workers 1 >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
) else (
    C:\Users\EdgarsTool\bin\op.exe run --env-file "%~dp0.env.op" -- python -m uvicorn server_fastapi:app --host 0.0.0.0 --port 8765 --workers 1 >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
)
