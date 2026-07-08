@echo off
REM TrackTW Poller — Windows Task Scheduler entrypoint
REM 用法：run-tracktw-poller.cmd {once|loop|status}
REM 預期由 Doppler 注入 TRACKTW_API_KEY / HOOKS_* 等環境變數

setlocal

set "POLLER_DIR=%~dp0..\"
pushd "%POLLER_DIR%"

REM 優先用 Doppler；若本機無 doppler CLI 也不會爆，由 python 自己 raise
where doppler >nul 2>nul && (
  echo [run-tracktw-poller] using Doppler secrets
  popd
  doppler run --project handcraft-mcp --config prd -- python "%POLLER_DIR%tracktw_poller.py" %*
  exit /b %ERRORLEVEL%
)

echo [run-tracktw-poller] Doppler not available, relying on env vars in caller context
popd
python "%POLLER_DIR%tracktw_poller.py" %*
exit /b %ERRORLEVEL%