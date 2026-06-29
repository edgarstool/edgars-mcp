# PR / Diff Review

請對指定的 PR 或 diff 做**風險審查**。不要逕自合併、不要關閉 PR。

## 檢查項

1. **安全**：
   - 是否引入硬編 secret / token / API key
   - 是否新增 `.env`、`*.pem`、`*.key` 等敏感檔
   - 是否擴大 GitHub Actions permissions
   - 是否關閉既有安全檢查
2. **路徑**：
   - 是否硬編 `C:\Users\EdgarsTool\Projects\<name>`（違反 EDGAR-OS）
   - 是否寫入 `D:\`（deprecated）
   - 是否把產物丟進 source tree
3. **正確性**：
   - 是否有遺漏 edge case
   - 是否處理錯誤
   - 是否有 N+1、無界迴圈、阻塞 IO
4. **測試 / 文件**：
   - 是否有對應 test
   - README / docs 是否同步更新
5. **CI / workflow**：
   - 新增 workflow 是否最小權限
   - schedule 是否有 `workflow_dispatch` 可手動觸發
   - 是否會 auto-merge、auto-deploy
6. **EDGAR-OS 合規**：
   - 是否違反 `AGENTS.md` / `.github/instructions/edgar-os.instructions.md`

## 回報格式（繁體中文）

```
Status:
Severity:                   (info / low / medium / high / critical)
Security Findings:
Path Findings:
Correctness Findings:
Test / Doc Findings:
CI Findings:
EDGAR-OS Compliance:
Suggested Changes:
Blocking Issues:            (必須修才能 merge)
Non-Blocking Suggestions:
Recommendation:             (approve / request changes / needs discussion)
```
