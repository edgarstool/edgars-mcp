# Edgar's MCP

Edgar's MCP is the single tool gateway behind Hermes and other MCP clients. It exposes 78 tools from one HTTP endpoint, including Warp Oz cloud-agent runs, Linear, Notion, Git, files, system inspection, browser automation, and AI-agent delegation.

The production defaults are deliberately narrow:

- listen on `127.0.0.1:8765`;
- keep mutable data under `~/runtime/edgars-mcp`;
- resolve `op://` references through a self-hosted 1Password Connect server;
- expose public traffic only through a separately managed ingress;
- preserve the existing MCP tool schemas.

## Contabo quick start

The recommended Contabo deployment is one private Docker Compose stack:

```text
1Password Connect API + Connect Sync + Edgar's MCP
```

Connect is self-hosted on Contabo and its REST API is bound only to `127.0.0.1:8080`, never to the public interface. The 1Password account and primary vault remain managed by 1Password; Connect keeps an encrypted synchronized copy for this stack.

Create a 1Password Secrets Automation Connect workflow for a dedicated shared vault such as `Edgar Cloud Agents`. Save the generated `1password-credentials.json` and an access token as separate files, then run:

```bash
git clone https://github.com/edgarstool/edgars-mcp.git \
  ~/workspaces/shared/30-services/edgars-mcp
cd ~/workspaces/shared/30-services/edgars-mcp
./deploy/docker/install.sh \
  /path/to/1password-credentials.json \
  /path/to/edgars-mcp.token
```

The installer stores only the two unavoidable Connect bootstrap files under `~/.config/1password-connect/` with private permissions, creates the runtime directories, and starts all three containers. Neither file belongs in Git.

Review the secret references for the `edgars-mcp` item:

```text
~/.config/edgars-mcp/edgars-mcp.op.env
```

Verify the finished service without printing a secret:

```bash
docker exec edgars-mcp /usr/local/bin/edgars-mcp-container-check
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

Choose one MCP mode per host because both MCP modes bind port 8765.

- Docker Compose: recommended for Contabo; includes the self-hosted Connect API and Sync containers.
- Native systemd: optional fallback; authenticates the CLI through a Connect token credential.
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
