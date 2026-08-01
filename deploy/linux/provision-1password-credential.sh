#!/usr/bin/env bash
set -euo pipefail

CONFIG_DIR="${EDGARS_MCP_CONFIG_DIR:-$HOME/.config/edgars-mcp}"
TARGET="$CONFIG_DIR/op-service-account-token.cred"

command -v systemd-creds >/dev/null 2>&1 || {
  echo "edgars-mcp: systemd-creds is required for encrypted unattended startup." >&2
  exit 1
}

mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
read -r -s -p "1Password service account token: " token
echo
if [[ -z "$token" ]]; then
  echo "edgars-mcp: token was empty; nothing changed." >&2
  exit 1
fi

printf '%s' "$token" | systemd-creds encrypt --user --name=op-service-account-token - "$TARGET"
unset token
chmod 600 "$TARGET"
echo "Encrypted credential written to $TARGET"

