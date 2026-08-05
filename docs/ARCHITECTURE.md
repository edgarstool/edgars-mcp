# Architecture

## Runtime boundary

`edgars-mcp` is one MCP gateway with two transports:

- HTTP server: `python -m edgars_mcp.http_server`
- stdio client bridge: `edgars-mcp-proxy`

Source code is immutable at runtime. All mutable data is routed through `RuntimePaths`:

| Data | Default path |
|---|---|
| PID and sockets | `~/runtime/edgars-mcp/run` |
| State and OAuth tokens | `~/runtime/edgars-mcp/state` |
| Logs | `~/runtime/edgars-mcp/logs` |
| Cache | `~/runtime/edgars-mcp/cache` |
| Temporary files | `~/runtime/edgars-mcp/tmp` |

Each path can be overridden independently with `EDGARS_MCP_RUN_DIR`, `EDGARS_MCP_STATE_DIR`, `EDGARS_MCP_LOG_DIR`, `EDGARS_MCP_CACHE_DIR`, or `EDGARS_MCP_TMP_DIR`.

## Capability inventory

| Capability | Linux | Windows | Notes |
|---|---:|---:|---|
| HTTP MCP and OAuth | Ready | Ready | Standard library; JWT verification is optional |
| Files, Git, shell, system info | Ready | Ready | Uses native shell and process tools |
| Warp Oz API | Ready | Ready | Requires `WARP_API_KEY` |
| Other external APIs | Ready | Ready | Each integration fails clearly when its key is absent |
| CLI agent delegation | Conditional | Conditional | Corresponding CLI must be installed and authenticated |
| Visible desktop browser | Unavailable headless | Conditional | Linux headless returns structured `unavailable` |
| Playwright browser tools | Conditional | Conditional | Install the `browser` optional dependency and browser runtime |

`tools/list` remains stable at 78 tools on both platforms. Runtime capability checks prevent a headless server from pretending it can open a visible desktop browser.

## Security boundary

- The server listens on loopback by default.
- `MCP_API_TOKEN` is mandatory and startup fails when it is absent.
- Secret values are injected at launch and are never stored in repository configuration.
- The recommended Contabo stack self-hosts `1password/connect-api` and `1password/connect-sync` beside Edgar's MCP.
- Connect is published only on host loopback (`127.0.0.1:8080`) for the native fallback and is never bound to the public interface; the Docker MCP reaches it by Compose service name.
- The MCP and Warp keys remain `op://` references and are resolved by `op run` through Connect.
- Only the Connect credentials JSON and a least-privilege Connect token bootstrap the stack; both are operator-owned files outside Git.
- Native systemd fallback loads the same Connect token as a systemd credential instead of using a 1Password service account.
- Public DNS, Cloudflare ingress, and TLS are intentionally outside this repository's install script.
