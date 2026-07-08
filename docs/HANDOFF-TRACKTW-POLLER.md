# TrackTW Poller + hooks.edgars.tools 整合 HANDOFF

> **TL;DR**：track.tw 沒有 webhook。我們本機跑一個 poller，每 20 分鐘把 watchlist 裡的單
> import → tracking → 比對快照 → 有變化就 POST `https://hooks.edgars.tools/tracktw`。
> Cloudflare Worker 收到後可選擇 HMAC 簽名驗證 + 轉發到 n8n / Hermes gateway / Discord。

---

## 三條替代方案（我選 A，n8n 為熱備）

| 方案 | 路徑 | 優 | 缺 | 我的選擇 |
|---|---|---|---|---|
| **A. 本機 poller → hooks** | tracktw_poller.py → POST hooks.edgars.tools/tracktw | 完全自控、不依賴第三方 | 本機要跑 daemon | ✅ 主路徑 |
| **B. n8n 自排程** | n8n cloudflare worker 每 20 分鐘打 track.tw + 推 hook | 雲端、不怕本機關機 | 多一層 worker | 🔥 熱備援 |
| **C. Make / Zapier** | 圖形化串接 | 最少自己寫 | 月費、Token 過境外部 | ❌ 不採用（付費 + 外部風險） |

**Make/Zapier 不採**：要付費、track.tw API key 與 tracking_number 都會過境外部 SaaS，
跟你「secure by default」偏好衝突。需要時再加。

---

## 已完成的程式碼

| 檔案 | 路徑 | 用途 |
|---|---|---|
| `tracktw_poller.py` | `V:/projects/edgars-mcp/tracktw-poller/` | 主程式（once / loop / status） |
| `config/tracktw_watchlist.json` | 同上 | 想追的單（手編） |
| `scripts/run-tracktw-poller.cmd` | 同上 | Windows Task Scheduler 包裝 |
| `hooks-worker/src/index.ts` | `V:/projects/cloudflared/hooks-worker/` | 加 `/tracktw` route（HMAC + timestamp 防 replay）|

---

## Doppler 設定（必須）

到 `handcraft-mcp` / `prd` 設：

```bash
doppler secrets set TRACKTW_API_KEY             --project handcraft-mcp --config prd   # 已有
doppler secrets set HOOKS_EDGARS_TOOLS_URL      --project handcraft-mcp --config prd
doppler secrets set HOOKS_EDGARS_TOOLS_TOKEN    --project handcraft-mcp --config prd   # 跟 worker 的 TRACKTW_WEBHOOK_SECRET 同值
```

`HOOKS_EDGARS_TOOLS_TOKEN` 的值 = Cloudflare Worker `TRACKTW_WEBHOOK_SECRET` secret。
**兩邊要對得起來**，不然 401。

可選（進階）：

```bash
TRACKTW_POLLER_INTERVAL_SEC=1200      # 預設 20 分鐘；測試可改 60
TRACKTW_POLLER_PARALLEL=4             # watchlist < 50 用預設即可
TRACKTW_HOOK_FORWARD_URL=https://...  # worker 收到後再轉發（n8n / Discord）
```

---

## Cloudflare Worker 部署（要 wrangler deploy）

```powershell
cd V:\projects\cloudflared\hooks-worker
wrangler secret put TRACKTW_WEBHOOK_SECRET      # 貼跟 HOOKS_EDGARS_TOOLS_TOKEN 同值
wrangler secret put TRACKTW_HOOK_FORWARD_URL   # 可選
wrangler deploy
```

**部署後**：

```powershell
# 驗 health 還是活的
curl https://hooks.edgars.tools/health
# → { ok: true, service: "edgar-hooks-inbox" }

# 沒簽名打 /tracktw → 應該 401 secret_not_configured 或 invalid_signature
curl -X POST https://hooks.edgars.tools/tracktw -d '{}'
# → { ok: false, error: "..." }

# 帶正確簽名 → 200
# (由 poller 自己打，不需要手動)
```

---

## Windows Task Scheduler 排程

```powershell
# 1. 確認 Doppler CLI 與 secret 都能在排程環境抓到
where doppler
doppler run --project handcraft-mcp --config prd -- python "V:\projects\edgars-mcp\tracktw-poller\tracktw_poller.py" status

# 2. 建立排程（每 20 分鐘跑一次）
$action = New-ScheduledTaskAction `
  -Execute "C:\projects\edgars-mcp\tracktw-poller\scripts\run-tracktw-poller.cmd" `
  -Argument "once"

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 20) `
  -RepetitionDuration (New-TimeSpan -Days 365)

Register-ScheduledTask -TaskName "TrackTW Poller" `
  -Action $action -Trigger $trigger `
  -User "SYSTEM" -RunLevel Highest `
  -Description "Polls track.tw every 20 min, posts changes to hooks.edgars.tools/tracktw"
```

驗證：

```powershell
Start-ScheduledTask -TaskName "TrackTW Poller"
Get-ScheduledTaskInfo -TaskName "TrackTW Poller"
Get-Content "G:\AI_WORK_512\cache\tracktw_poller\poller.log" -Tail 30
```

---

## 手動驗證鏈路（不排程）

```powershell
cd V:\projects\edgars-mcp\tracktw-poller

# 跑一輪（會建 baseline snapshot，不會 POST）
doppler run --project handcraft-mcp --config prd -- python tracktw_poller.py once

# 改 hash 模擬變化 → 再跑一次 → 應該 POST 到 hook
python -c "import json; p=r'G:\AI_WORK_512\cache\tracktw_poller\state.json'; s=json.load(open(p)); k=list(s.keys())[0]; s[k]['last_event_hash']='deadbeef'+s[k]['last_event_hash'][8:]; json.dump(s, open(p,'w',encoding='utf-8'), indent=2, ensure_ascii=False)"

doppler run --project handcraft-mcp --config prd -- python tracktw_poller.py once
# → log 應有 CHANGED + "→ hook: ok=True status=200"（前提：worker 已 deploy）
```

---

## Hook payload schema

POST `https://hooks.edgars.tools/tracktw` body：

```json
{
  "event": "package.changed",
  "tracking_number": "T1234567890",
  "carrier_name": "7-Eleven店到店",
  "carrier_id": "9a980809-8865-4741-9f0a-3daaaa7d9e19",
  "label": "給人看的標籤",
  "package_uuid": "212bcf67-...",
  "latest_state": "已到達門市",
  "event_count": 5,
  "observed_at": "2026-07-08T10:36:48.717+00:00",
  "previous": {
    "latest_state": "已出貨",
    "event_count": 4,
    "last_event_hash": "abc123...",
    "last_checked_at": "2026-07-08T10:16:48.000+00:00"
  }
}
```

Headers：

```
X-TrackTW-Webhook-Signature: sha256=<hex>
X-TrackTW-Webhook-Timestamp: <unix-seconds>
Content-Type: application/json
```

Worker 端驗證：HMAC-SHA256 over `${timestamp}.${body}`，timestamp 必須在 ±5 分鐘內（防 replay）。

---

## n8n 熱備援（可選）

若本機 poller 掛了，雲端 n8n 可以每 20 分鐘打一次同樣的 watchlist，比對上次 hash，
有變化也 POST 到 hooks（或直接送到 Discord）。

```bash
# 在 n8n cloudflare worker 建立 workflow：
# Schedule Trigger (every 20 min)
#   → HTTP Request: GET track.tw /carrier/available（拿 carrier_id cache）
#   → Loop over watchlist
#     → HTTP Request: POST track.tw /package/import
#     → HTTP Request: GET track.tw /package/tracking/{uuid}
#     → IF (hash 變化)
#       → HTTP Request: POST hooks.edgars.tools/tracktw (帶同樣 HMAC 簽名)
#     → Save state to n8n KV / 外部 store
```

---

## 已知限制

- **track.tw 真正貨態更新延遲**：5–60 分鐘（不是我們能控制的）。20 分鐘 polling 是保險。
- **無 expiry endpoint**：key 過期只能從 HTTP 401/403 判斷。建議每 90 天輪換。
- **無 callback_url**：之前實測帶 `callback_url` import 端被忽略（200 OK 但不 push）。
- **worker 部署後**才會看到 200；現在 403 = CDN 層擋（CF Access / Bot Fight）。

## Risks

- 本機關機時只有 n8n 熱備運作（建議 n8n 永遠開著作為 fallback）
- watchlist 過大會拖慢 polling（>50 單時可分批或加 worker 數）
- Doppler 沒注入 → poller 會在第一輪就 raise（明確錯誤、不會靜默壞掉）