#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for edgars-mcp (handcraft-mcp).
# Runs after the repository is checked out. Safe to run repeatedly.
set -euo pipefail

cd "$(dirname "$0")/.."

# ── Python dependencies ──────────────────────────────────────────────────────
# requirements.txt pins the optional runtime integrations (playwright, descope).
# jsonschema + PyJWT are required by the test suite and by the Cloudflare Access
# auth mode of server_http.py, but are not listed in requirements.txt.
python3 -m pip install --user -r requirements.txt jsonschema PyJWT

# ── PowerShell ───────────────────────────────────────────────────────────────
# This repo is PowerShell-centric (scripts/*.ps1 plus a test that shells out to
# `powershell`). Install PowerShell 7 only when it is missing so builds that boot
# from a snapshot skip this step.
if ! command -v pwsh >/dev/null 2>&1; then
  PWSH_VER="7.4.6"
  case "$(dpkg --print-architecture)" in
    arm64) PKG="powershell-${PWSH_VER}-linux-arm64.tar.gz" ;;
    *)     PKG="powershell-${PWSH_VER}-linux-x64.tar.gz" ;;
  esac
  tmp="$(mktemp -d)"
  curl -fsSL -o "${tmp}/powershell.tar.gz" \
    "https://github.com/PowerShell/PowerShell/releases/download/v${PWSH_VER}/${PKG}"
  sudo mkdir -p /opt/microsoft/powershell/7
  sudo tar zxf "${tmp}/powershell.tar.gz" -C /opt/microsoft/powershell/7
  sudo chmod +x /opt/microsoft/powershell/7/pwsh
  sudo ln -sf /opt/microsoft/powershell/7/pwsh /usr/local/bin/pwsh
  sudo ln -sf /opt/microsoft/powershell/7/pwsh /usr/local/bin/powershell
  rm -rf "${tmp}"
fi

echo "install.sh complete: python deps + pwsh $(pwsh --version 2>/dev/null || echo 'missing')"
