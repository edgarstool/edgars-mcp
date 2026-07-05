@echo off
setlocal
set "LOGDIR=%~dp0logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
    doppler run --project handcraft-mcp --config prd -- py -3 "%~dp0server_http.py" >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
) else (
    python "%~dp0scripts\rotate-http-logs.py" >nul 2>nul
    doppler run --project handcraft-mcp --config prd -- python "%~dp0server_http.py" >> "%LOGDIR%\handcraft-http.out.log" 2>> "%LOGDIR%\handcraft-http.err.log"
)
