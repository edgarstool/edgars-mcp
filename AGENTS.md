# Repository agent guide

## Goal

Keep `edgars-mcp` a deployable, cross-platform MCP gateway. Prefer a finished, verified artifact over open-ended exploration.

## Invariants

- Preserve the externally visible MCP tool names and schemas unless a breaking change is explicitly approved.
- Keep source under `src/edgars_mcp` and tests under `tests`.
- Keep mutable runtime data outside the checkout through `RuntimePaths`.
- Default network binding is `127.0.0.1:8765`.
- Never commit secret values. Production secret references belong in `config/edgars-mcp.op.env.example`.
- Do not change public ingress, DNS, or production Cloudflare configuration from repository install scripts.
- Use platform-neutral paths; derive user locations from `$HOME`, `%USERPROFILE%`, or environment overrides.

## Verification

Run before claiming completion:

```bash
python -m unittest discover -s tests -v
python -m build
```

When Docker is available, also build the image and run the Compose configuration check.
