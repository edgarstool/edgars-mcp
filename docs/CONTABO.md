# Contabo deployment

The canonical native layout is:

| Purpose | Path |
|---|---|
| Source | `/home/edgar/workspaces/shared/30-services/edgars-mcp` |
| Non-secret config | `/home/edgar/.config/edgars-mcp` |
| Runtime | `/home/edgar/runtime/edgars-mcp` |
| User service | `/home/edgar/.config/systemd/user/edgars-mcp.service` |

## Native systemd mode

Prerequisites: Python 3.11+, 1Password CLI, systemd user services, and `systemd-creds` for unattended restart.

```bash
cd /home/edgar/workspaces/shared/30-services/edgars-mcp
./deploy/linux/install.sh
```

Edit only the 1Password reference names in:

```text
~/.config/edgars-mcp/edgars-mcp.op.env
```

Provision the bootstrap credential interactively and start:

```bash
./deploy/linux/provision-1password-credential.sh
systemctl --user start edgars-mcp
systemctl --user status edgars-mcp
```

Enable user services after logout or reboot:

```bash
loginctl enable-linger edgar
```

That last command may require an administrator once.

## Verification

```bash
op run --env-file ~/.config/edgars-mcp/edgars-mcp.op.env -- \
  ./deploy/linux/check.sh
journalctl --user -u edgars-mcp -n 100 --no-pager
```

The check verifies `/health`, exactly 78 registered tools, and all three Warp Oz tools.

## Docker mode

Stop the native service first because both modes use port 8765:

```bash
systemctl --user disable --now edgars-mcp
mkdir -p ~/runtime/edgars-mcp/{run,state,logs,cache,tmp}
op run --env-file ~/.config/edgars-mcp/edgars-mcp.op.env -- \
  docker compose -f deploy/docker/compose.yaml up -d --build
```

Compose receives `MCP_API_TOKEN` and `WARP_API_KEY` only long enough to create Docker secret mounts. They are not written into the image or Compose file.

## Scope boundary

Installation stops at a healthy loopback service. Pointing `mcp.edgars.tools` or changing the Cloudflare production tunnel is a separate production change and requires its own verification.

