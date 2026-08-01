# Edgar's MCP

Edgar's MCP is the single tool gateway behind Hermes and other MCP clients. It exposes 78 tools from one HTTP endpoint, including Warp Oz cloud-agent runs, Linear, Notion, Git, files, system inspection, browser automation, and AI-agent delegation.

The production defaults are deliberately narrow:

- listen on `127.0.0.1:8765`;
- keep mutable data under `~/runtime/edgars-mcp`;
- inject secrets from 1Password at process start;
- expose public traffic only through a separately managed ingress;
- preserve the existing MCP tool schemas.

## Contabo quick start

Use the canonical checkout:

```bash
git clone https://github.com/edgarstool/edgars-mcp.git \
  ~/workspaces/shared/30-services/edgars-mcp
cd ~/workspaces/shared/30-services/edgars-mcp
./deploy/linux/install.sh
```

Create an `edgars-mcp` item in the `Edgar Cloud Agents` 1Password vault, then review:

```text
~/.config/edgars-mcp/edgars-mcp.op.env
```

For unattended restarts, store only the 1Password service-account bootstrap token as a systemd encrypted credential:

```bash
./deploy/linux/provision-1password-credential.sh
systemctl --user start edgars-mcp.service
```

Verify the finished service without printing a secret:

```bash
op run --env-file ~/.config/edgars-mcp/edgars-mcp.op.env -- \
  ./deploy/linux/check.sh
```

Expected result:

```text
PASS: health, 78 tools, Warp Oz tools
```

## Warp Oz tools

Warp is already part of this gateway. No separate bridge or terminal installation is required.

| MCP tool | Result |
|---|---|
| `warp_agent_run_create` | Start an Oz cloud-agent run |
| `warp_agent_run_status` | Read run status and result |
| `warp_agent_runs_list` | List recent runs |

The only Warp secret is `WARP_API_KEY`, injected from the same 1Password item.

## Deployment modes

Choose one mode per host; both bind the same port.

- Native systemd: recommended for Contabo and local CLI integrations.
- Docker Compose: isolated runtime; start it through `op run` so Compose can create Docker secrets.
- Windows PowerShell: supported from `deploy/windows/` without fixed drive letters.

See [Contabo deployment](docs/CONTABO.md), [architecture](docs/ARCHITECTURE.md), and [Windows](docs/WINDOWS.md).

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[all]'
python -m unittest discover -s tests -v
```

Run directly:

```bash
MCP_API_TOKEN=test-token python -m edgars_mcp.http_server
```
