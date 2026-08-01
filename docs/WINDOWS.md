# Windows

Windows is a supported client and development platform, but it does not define the cloud runtime layout.

```powershell
.\deploy\windows\install.ps1
.\deploy\windows\start.ps1
```

Paths are derived from the checkout, `%USERPROFILE%`, and `%LOCALAPPDATA%`. Override them with:

- `EDGARS_MCP_SOURCE_DIR`
- `EDGARS_MCP_CONFIG_DIR`
- `EDGARS_MCP_RUNTIME_DIR`

Run the authenticated check in another shell:

```powershell
op run --env-file "$HOME\.config\edgars-mcp\edgars-mcp.op.env" -- \
  powershell -File .\deploy\windows\check.ps1
```

Stop only the Python process whose command line contains `edgars_mcp.http_server`:

```powershell
.\deploy\windows\stop.ps1
```

