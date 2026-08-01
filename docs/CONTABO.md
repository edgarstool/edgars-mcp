# Contabo deployment

## Finished topology

The recommended deployment is a single Docker Compose stack:

| Service | Purpose | Exposure |
|---|---|---|
| `op-connect-api` | Private 1Password Connect REST API | `127.0.0.1:8080` and Compose network |
| `op-connect-sync` | Synchronizes the encrypted Connect cache with 1Password | Outbound only |
| `edgars-mcp` | 78-tool MCP gateway, including three Warp Oz tools | `127.0.0.1:8765` |

Cloudflare ingress, DNS, and the live `mcp.edgars.tools` route remain separate production changes.

## One-time 1Password preparation

Create a Secrets Automation Connect workflow in 1Password for a dedicated shared vault such as `Edgar Cloud Agents`. Connect cannot use a built-in Personal, Private, Employee, or default Shared vault.

Keep the two generated bootstrap artifacts as separate files:

- `1password-credentials.json`: starts the Connect API and Sync containers.
- `edgars-mcp.token`: least-privilege Connect access token for this MCP service.

The normal application secrets remain fields in the `edgars-mcp` item and are referenced by `config/edgars-mcp.op.env.example`.

## Install

Prerequisites: Docker Engine with Docker Compose, the two bootstrap files, and the canonical checkout:

```text
/home/edgar/workspaces/shared/30-services/edgars-mcp
```

Run:

```bash
cd /home/edgar/workspaces/shared/30-services/edgars-mcp
./deploy/docker/install.sh \
  /path/to/1password-credentials.json \
  /path/to/edgars-mcp.token
```

The installer copies the bootstrap files to:

```text
/home/edgar/.config/1password-connect/1password-credentials.json
/home/edgar/.config/1password-connect/edgars-mcp.token
```

The directory uses mode `0700`; both files use mode `0600`. They are excluded from Git. The installer preserves an existing `~/.config/edgars-mcp/edgars-mcp.op.env` and creates it from the reference template only when absent.

## Verification

```bash
docker compose -f deploy/docker/compose.yaml ps
docker exec edgars-mcp /usr/local/bin/edgars-mcp-container-check
```

The second command resolves `MCP_API_TOKEN` through the self-hosted Connect API, then verifies `/health`, exactly 78 tools, and all three Warp tools. Expected result:

```text
PASS: health, 78 tools, Warp Oz tools
```

## Native fallback

Native systemd mode remains available for integrations that require a host Python process:

```bash
./deploy/linux/install.sh
systemctl --user start edgars-mcp.service
```

It expects Connect at `http://127.0.0.1:8080` and loads `~/.config/1password-connect/edgars-mcp.token` as a systemd credential. Do not run native and Docker MCP modes simultaneously because both bind port 8765.

## Boundary

This repository prepares and verifies a loopback service. It does not modify the live Contabo host, Cloudflare Tunnel, Access policy, DNS, or production secrets by itself.
