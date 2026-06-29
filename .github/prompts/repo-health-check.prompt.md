# Repo Health Check

Perform a **read-only** repository health check.

## Check

- README accuracy
- setup instructions
- test commands
- build commands
- stale TODO / FIXME
- suspicious generated files in source tree
- dependency files (lockfile / version drift)
- GitHub Actions workflows
- EDGAR-OS path compliance (no hard-coded `C:\Users\EdgarsTool\Projects\`, no `D:\` as entry)
- possible secret-like filenames **only** (`*.env`、`*.pem`、`*.key`、`id_rsa*`、`1password*`、`doppler*`)
  — **do not open secrets**

## Rules

- Do **not** modify files.
- Do **not** commit.
- Do **not** create branches.
- Use Traditional Chinese in the report.

## Return

```
Status:
Findings:
  README:
  Setup:
  Tests:
  Build:
  TODO / FIXME:
  Generated Files:
  Dependencies:
  Workflows:
  EDGAR-OS Compliance:
  Secret-Like Filenames:       (僅檔名清單)
Risks:
Suggested Actions:
Can Be Automated:              (列出可變 GitHub Actions / Copilot Automation 的項目)
Needs User Confirmation:       (列出需確認的項目)
```
