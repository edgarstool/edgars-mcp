---
applyTo: "**/*.ps1,**/*.psm1,**/*.psd1,**/*.cmd,**/*.bat"
---

# Windows / PowerShell 任務規則

本檔套用在所有 PowerShell 與 batch 檔案。

## Shell 預設

- 一律使用 **PowerShell**（pwsh 7+ 優先；fallback Windows PowerShell 5.1）。
- 不要假設 bash / zsh，除非任務明確跨到 WSL / Linux / VPS。
- 不要假設使用者人在 macOS / Linux。

## 編碼

- 檔案使用 **UTF-8**（含 BOM 為佳，能避免 Windows PowerShell 5.1 中文亂碼）。
- script 內若要輸出中文，建議：
  ```powershell
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
  $OutputEncoding = [System.Text.Encoding]::UTF8
  ```

## 路徑

- 一律使用 Windows 風格絕對路徑（`V:\projects\<name>`）。
- 不要硬編 `C:\Users\EdgarsTool\Projects\<name>`，改用 `V:\projects\<name>`。
- 不要使用 `D:\` 作正式入口。
- tmp / cache / 大檔產出請落到 `G:\AI_WORK_512\<scope>\`。

## 安全

- 不要在 script 內硬編 secret。
- secret 來源優先順序：1Password CLI → Doppler → Cloudflare Secrets → env injection。
- 不要 `Invoke-Expression` 不可信輸入。
- 不要 `-ExecutionPolicy Bypass` 之外的政策變更；必要時 `Bypass` 只給單一 script 範圍。

## 風格

- 函式命名用 PowerShell `Verb-Noun`（例如 `Get-RepoHealth`）。
- 參數用 `[CmdletBinding()]` + `param()`。
- 錯誤處理用 `try/catch`，並 `Write-Error` + 適當 `exit code`。
- 長時間任務支援 `-WhatIf` / `-Confirm`。
- 若 script 會改檔，預設 dry-run，需要 `-Apply` 才實際執行。

## 不要做

- 不要 `rm -rf` 風格遞迴刪除未經確認。
- 不要無腦 `Start-Process -Verb RunAs`。
- 不要動 registry 未經確認。
- 不要動 production cloudflared、production tunnel、production DNS。
