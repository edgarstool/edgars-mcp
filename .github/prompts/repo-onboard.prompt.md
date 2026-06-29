# Repo Onboarding

請以**唯讀**模式快速理解本 repo。**不要改檔、不要 commit、不要建立 branch**。

## 步驟

1. 讀 `README.md`、`README.*`、`docs/` 的入口檔。
2. 讀 package 設定（`package.json`、`pyproject.toml`、`requirements.txt`、`Cargo.toml`、`go.mod`、`*.csproj` 等）。
3. 讀 config（`.env.example`、`config/`、`*.yaml`、`*.toml`、`*.json`）。
4. 讀 tests 目錄結構與 CI workflow（`.github/workflows/`）。
5. 讀 `AGENTS.md`、`.github/copilot-instructions.md`、`.github/instructions/*`。

## 請以繁體中文回報

```
Status:
Repo Type:                  (web app / CLI / library / ops / docs / unknown)
Entry Points:               (主要入口檔)
How To Run:                 (本機如何跑)
How To Test:                (測試指令)
How To Build:               (建置指令)
Key Dependencies:           (主要套件 / runtime 版本)
CI / Workflows:             (現有 GitHub Actions)
Risks Spotted:              (可疑路徑 / 疑似 secrets 檔名 / 偏離 EDGAR-OS)
Open Questions:             (需要使用者確認的問題)
```

## 禁止

- 不要開啟疑似 secret 檔案（`.env`、`*.pem`、`*.key`、`id_rsa*`、`1password*`、`doppler*`）。
- 不要假設 repo root 在 `C:\Users\EdgarsTool\Projects\<name>`。
- 不要假設 `D:\` 為入口。
