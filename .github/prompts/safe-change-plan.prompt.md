# Safe Change Plan

在實際改檔之前，請先產出**改檔計畫**並等使用者確認。**不要直接動檔案**。

## 請回報

```
Status:                     (planning)
Goal:                       (這次改檔要達到什麼)
Approach Options:           (列 1–3 種方案，附優缺點)
Chosen Approach:            (建議哪一個)
Files To Add:               (新增清單)
Files To Modify:            (修改清單，每檔說明會動哪段)
Files To Delete:            (刪除清單)
Side Effects:               (對其他模組 / API / DB / 環境變數的影響)
Verification Plan:          (改完如何驗證：test / lint / smoke / 手動步驟)
Rollback Plan:              (出錯如何還原)
Risks:                      (風險等級 + 風險點)
Needs User Confirmation:    (yes / no)
Next:                       (等使用者說 OK 後第一個會跑的動作)
```

## 規則

- 列方案要有取捨，不要單方案硬推。
- 沒有 verification 不算完整計畫。
- 沒有 rollback 不算完整計畫。
- 動 secrets、production、CI 權限、deploy、DNS、cloudflared、tunnel 一律 `Needs User Confirmation: yes`。
- 計畫核可後才能進實作；實作完先回報狀態，再決定是否 commit。

請使用繁體中文回覆。
