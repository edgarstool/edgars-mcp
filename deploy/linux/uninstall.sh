#!/usr/bin/env bash
set -euo pipefail

UNIT="$HOME/.config/systemd/user/edgars-mcp.service"
systemctl --user disable --now edgars-mcp.service 2>/dev/null || true
if [[ -e "$UNIT" ]]; then
  mv "$UNIT" "$UNIT.disabled"
fi
systemctl --user daemon-reload
echo "edgars-mcp service removed. Source, configuration, encrypted credential, and runtime data were preserved."

