@echo off
setlocal
:: Headless secrets: local Connect on 8877. Deleted SA token in the parent env
:: would 403 if Connect host is missing; Connect vars take precedence when both set.
set "OP_CONNECT_HOST=http://127.0.0.1:8877"
set "OP_SERVICE_ACCOUNT_TOKEN="
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
    C:\Users\EdgarsTool\bin\op.exe run --env-file "%~dp0.env.op" -- py -3 "%~dp0server_http.py" >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
) else (
    python "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
    C:\Users\EdgarsTool\bin\op.exe run --env-file "%~dp0.env.op" -- python "%~dp0server_http.py" >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
)