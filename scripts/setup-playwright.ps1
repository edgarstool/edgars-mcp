# Install Playwright for the same Python that runs mcp-handcraft (py -3).
# Usage:
#   cd V:\projects\edgars-mcp
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-playwright.ps1

$ErrorActionPreference = "Stop"
Set-Location "V:\projects\edgars-mcp"

Write-Host "[setup-playwright] Installing Python package..."
py -3 -m pip install -r .\requirements.txt

Write-Host "[setup-playwright] Installing Chromium for headless browser_* tools..."
py -3 -m playwright install chromium

Write-Host "[setup-playwright] Verifying import..."
py -3 -c "from playwright.sync_api import sync_playwright; print('playwright ok')"

Write-Host "[setup-playwright] Done. Visible browser tools use installed Chrome (channel=chrome)."
