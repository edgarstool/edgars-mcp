@echo off
setlocal
doppler run --project edgars-mcp --config prd -- py -3 "%~dp0server.py"
