#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "Usage: $0 /path/to/1password-credentials.json /path/to/edgars-mcp.token" >&2
  exit 2
fi

credentials_source="$1"
token_source="$2"
target_dir="${OP_CONNECT_CONFIG_DIR:-$HOME/.config/1password-connect}"

if [[ ! -r "$credentials_source" ]]; then
  echo "1Password Connect credentials file is missing or unreadable: $credentials_source" >&2
  exit 1
fi
if [[ ! -r "$token_source" ]]; then
  echo "1Password Connect token file is missing or unreadable: $token_source" >&2
  exit 1
fi

install -d -m 0700 "$target_dir"
install -m 0600 "$credentials_source" "$target_dir/1password-credentials.json"
install -m 0600 "$token_source" "$target_dir/edgars-mcp.token"

echo "1Password Connect bootstrap files installed in $target_dir"
