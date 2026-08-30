@echo off
setlocal
:: Doppler abandoned. Secrets via 1Password Connect (8877) + op run --env-file.
set "OP_SERVICE_ACCOUNT_TOKEN="
set "OP_CONNECT_HOST=http://127.0.0.1:8877"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    C:\Users\EdgarsTool\bin\op.exe run --env-file "%~dp0.env.op" -- py -3 "%~dp0server.py"
) else (
    C:\Users\EdgarsTool\bin\op.exe run --env-file "%~dp0.env.op" -- python "%~dp0server.py"
)
