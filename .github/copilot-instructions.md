# Copilot instructions

- Preserve the 78-tool MCP contract unless the issue explicitly authorizes a schema change.
- Use `src/edgars_mcp` for application code and `tests` for tests.
- Keep runtime data outside the Git checkout via `RuntimePaths`.
- Use cross-platform Python first; isolate OS-specific code behind explicit capability checks.
- Never add real tokens or credentials. Use 1Password reference examples only.
- Do not alter production ingress or merge a deployment branch automatically.
- Verify tests, package build, and available deployment checks before opening a pull request.
