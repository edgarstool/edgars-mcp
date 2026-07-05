---
title: 小抄 — 之後想「Cloudflare 登入、免 token」時照做
created: 2026-07-04
tags: [mcp, cloudflare, 授權, 小抄]
---

# 小抄：想讓 mcp.edgars.tools「登入一次、免打 token」時照做

> 現在**不用做**。這張是「哪天想切換時」的照做清單。平常 agent 走 OAuth（授權一次就記住），你只看儀表板即可。

## 現況（我查到的事實）
- 保護 `mcp.edgars.tools` 的 Access 應用叫 **`edgar-mcp-local`**
  - 應用 ID：`0f5b2f6b-bb20-403b-92b3-5447ffc4b7f5`
  - 目前政策：**Bypass MCP OAuth（＝不驗證、全部放行）** → 所以不會跳登入，token 由 server 自己在擋。
- 你的 **team domain：`edgarstools.cloudflareaccess.com`**
- Google / GitHub / iCloud 登入方式**都已備好**，且該應用設成「接受所有識別提供者」→ 一旦要登入，這三個都會出現讓你選。
- **PR #26（授權全綠）已合併進 master** ✅（server 下次重啟跑到 master 就生效）。

## 要「登入免 token」＝兩邊都要做

### A. Cloudflare 這邊（把 Bypass 換成要登入）
在 Zero Trust → Access 控制 → 應用程式 → 點 `edgar-mcp-local` → Access 原則：
1. 刪掉那條「Bypass MCP OAuth」。
2. 建立新原則：動作 **Allow** → 規則 **Emails** → 填你的 email（只有你能登入）。
3. 「認證」區確認「接受所有可用的識別提供者」開著（Google/GitHub/iCloud 就都會出現）。
4. **（重要）** 再建一條：動作 **Allow** → 規則 **Service Token** → 選你的 token
   →這樣 n8n／腳本等「不能登入」的機器客戶端才不會被擋。
5. 按「儲存」。

### B. Server 這邊（讓 server 信任 Cloudflare 的登入）
在 Doppler（或 server 的環境變數）設：
```
CF_ACCESS_TEAM_DOMAIN = edgarstools.cloudflareaccess.com
CF_ACCESS_AUD = <從 edgar-mcp-local 的 AUD 標籤複製；要時叫我幫你抓>
```
然後確認 server 跑的是 master（含已合併的 PR #26），**重啟 server**。

> AUD 在哪：Zero Trust → 該應用 → 設定裡的「Application Audience (AUD) Tag」。要時我用 Chrome 幫你抓。

## 做完的效果
打開 `mcp.edgars.tools` → 跳 Cloudflare 登入（Google/GitHub/iCloud 任選）→ 登入一次
→ server 信任這個登入 → **不再要 token**。機器客戶端則走 Service Token。

## ⚠️ 風險提醒
- 改成「要登入」後，**不能做瀏覽器登入的客戶端會被擋** → 一定要記得做 A 的第 4 步（Service Token）。
- 這是改 production 授權，改完要實測：CF 登入能過、Service Token 能過、沒憑證被擋。
- 你也可以**完全不改**：現在 agent 走 OAuth 授權一次就好，本來就沒有每次打密碼的問題。

## 一句話
平常不用動。想要「人用瀏覽器登入免 token」那天，照 A + B 做，AUD 叫我抓，5 分鐘搞定。
