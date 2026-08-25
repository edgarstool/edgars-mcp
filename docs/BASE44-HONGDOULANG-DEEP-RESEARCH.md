# Executive Decision

Should we use Base44 for the 14-day 烘豆廊 sprint?

**YES WITH CONDITIONS**

Base44 能在 Week 1 做出完整 Demo，速度快、視覺好、Commerce 有 Stripe PoC 路徑。但 Portability 有明確上限：Export 出來的是 frontend code，後端/資料庫/Auth 仍綁 Base44 SDK。因此接受 Base44 的條件是：Week 1 只拿它做 Demo + Day 7 驗收；若通過，Week 2 立刻建立 GitHub export 主權備份，同時規劃 production hosting + 台灣金流接真，最終上線前必須離開 Base44 backend。

# Recommended Subscription Strategy

- Week 1：**Free plan 做 Demo 驗證**
- Day 7 若通過：升級 **Builder monthly**（$50/mo）至少 1 個月，目的是 custom domain + GitHub 2-way sync + backend functions
- **iOS App Store weekly 不建議**：台灣 App Store 只有年付/高價 in-app purchase 選項，未見明確 weekly 方案；且 web subscription 與 App Store 是否共用 credits 官方未明說
- 最多付 **2 週**，Week 2 結束後若未進入 production migration，立即取消
- Day 14 必須完成 export + backup，subscription 只在「需要 Builder 功能」時保留

# Base44 Capability Matrix

| 面向 | 狀態 | 限制 |
|------|------|------|
| React / framework | NATIVE | Base44 runtime，非標準 Next/Vite |
| Routing | NATIVE | 平台內建 |
| Responsive / mobile | NATIVE | 內建 responsive editor |
| Custom components | SUPPORTED WITH CODE | Builder+ 可寫 code |
| Custom CSS | NATIVE | 視覺編輯器支援 |
| Raw code editing | NATIVE | Builder+ |
| npm packages | UNKNOWN | 未見官方確認 |
| Third-party JS SDK | SUPPORTED WITH CODE | 透過 code editing |
| Database | NATIVE | 平台托管，非 portable |
| Database schema | NATIVE | AI 可生成，但鎖在 Base44 |
| Relationships | NATIVE | 平台內建 |
| Auth | NATIVE | 平台內建，非 portable |
| Roles / permissions | NATIVE | 平台內建 |
| File storage | NATIVE | Base44 storage |
| Serverless functions | NATIVE | Builder+，但綁平台 runtime |
| Secrets / env | NATIVE | 平台管理 |
| Scheduled jobs | UNKNOWN | 未見官方確認 |
| Webhooks | SUPPORTED WITH CODE | 可能透過 integrations |
| REST API | UNKNOWN | 未見明確文件 |
| External API | NATIVE | 有 connectors/integrations |
| Realtime | UNKNOWN | 未見官方確認 |
| Product catalog | SUPPORTED WITH CODE | 可做，但無明確 commerce schema |
| Cart / Checkout | SUPPORTED WITH CODE | Stripe 有官方文件 |
| Orders / Inventory | SUPPORTED WITH CODE | 需自建資料表 + logic |
| Stripe | NATIVE | AI chat 直接設定 |
| Stripe Sandbox | NATIVE | 可用 test keys |
| Custom payment | UNKNOWN | 需 code，文檔不足 |
| SEO metadata | NATIVE | 內建支援 |
| Sitemap / robots | UNKNOWN | 未見官方確認 |
| Structured data | SUPPORTED WITH CODE | 可手動加 |
| Custom domain | NATIVE | Builder+ |
| Logs / monitoring | NATIVE | 內建 analytics |
| Rollback | NATIVE | Version History |
| Staging / preview | NATIVE | 內建 preview |
| Analytics | NATIVE | 內建 |

# Pricing & iOS Billing

## Web Pricing（官方 source，查證 2026-08-19）

| 方案 | 月付 | 年付 | Message Credits | Integration Credits |
|------|------|------|-----------------|---------------------|
| Free | $0 | $0 | 25/mo | 100/mo |
| Starter | $20 | $16 | 100/mo | 2,000/mo |
| Builder | $50 | $40 | 250/mo | 10,000/mo |
| Pro | $100 | $80 | 500/mo | 20,000/mo |
| Elite | $200 | $160 | 1,200/mo | 50,000/mo |

- Credits 不累積，每月重置
- Free plan 每日上限 5 message credits
- 取消訂閱後：功能維持到 billing period 結束，之後降級；apps 仍 live，資料仍保留

## iOS App Store（台灣，查證 2026-08-19）

**官方 App：**
- 「Base44: Build with AI」by BASE44 LTD（id: 6757432427）
- 台灣 App Store 有上架，支援繁體中文
- 顯示 in-app purchases：
  - Starter plan: $690 TWD（可能是年付或 lifetime？官方未明）
  - Builder plan: $1,490 TWD
  - Pro plan: $2,990 TWD
  - Elite: $6,990 TWD
- **未見明确的 weekly 訂閱方案**
- 另一個 id 6764797516 是第三方克隆 app，非官方

**Web 與 App Store subscription 是否共用：**
- 官方未明確說明
- 推測：App Store 年付/終身買斷可能對應 web yearly，但 credits 共用關係 UNKNOWN

# GitHub / Export / Portability

## 官方確認（查證 2026-08-19）

- GitHub 2-way sync **需要 Builder plan+**
- 本地開發：clone repo → npm install → npm run dev
- 環境變數：VITE_BASE44_APP_ID、VITE_BASE44_APP_BASE_URL
- 連接後自動同步，無手動 push 按鈕
- **GitHub sync 是永久性的，無法 disconnect 後 reconnect 到同一 repo**
- disconnect 後 30 秒生效，但無法連回相同 repo 名稱

## 社群經驗（分類）

- MULTIPLE USER REPORTS：Export 出來的是 bare Vite/React app，缺少 auth/backend/integrations
- MULTIPLE USER REPORTS：Exported code 仍依賴 @base44/sdk，無法獨立運行
- MULTIPLE USER REPORTS：Base44 backend 無法 export，資料庫鎖在平台
- SINGLE USER REPORT：Reddit 用戶稱可透過 swap SDK 離開，但需重寫關鍵部分
- CONFIRMED BY OFFICIAL DOCS：官方說 "you own everything"，但細則寫 "Two-way GitHub sync exports the full source code to your own repo at any time. Nothing is locked to the platform." — 與社群體驗有落差

## Dependency Graph

```
Frontend (React)
    ↓
Base44 SDK
    ↓
Auth ← Base44 Auth
Database ← Base44 Database
Storage ← Base44 Storage
Functions ← Base44 Functions
Realtime ← Base44 Realtime
```

## 回答核心問題

**A. 「拿到 source code」是否等於真正可離開 Base44？**
否。拿到的是 frontend code，仍依賴 Base44 SDK 才能連接後端服務。

**B. 若停止 Base44 subscription，哪些東西還能工作？**
- Apps 仍 live（官方說法）
- GitHub repo 仍可存取
- 但 exported code 若依賴 Base44 SDK，無法獨立部署運行

**C. 要完全離開 Base44，最少需要替換哪些服務？**
- Base44 DB → Supabase / Postgres
- Base44 Auth → Supabase Auth / Clerk / Auth.js
- Base44 Functions → Vercel Functions / Cloudflare Workers
- Base44 Storage → Cloudinary / R2 / S3
- Base44 SDK → 移除，改用標準 React + 自寫 API layer

**D. 有沒有官方 migration path？**
否。官方只有 export + GitHub sync，沒有自動 migration 工具或文件。

# Vendor Lock-in Dependency Map

```
[High Lock-in]
├── Base44 Database（無法 export schema + data）
├── Base44 Auth（用戶資料、session、permissions）
├── Base44 Functions（serverless runtime）
├── Base44 Storage（檔案）
└── Base44 SDK（前端依賴）

[Medium Lock-in]
├── Base44 Analytics
├── Base44 Integrations（Stripe 設定在平台內）
└── Base44 Version History

[Low Lock-in / Portable]
├── Frontend UI code（React components）
├── Custom CSS
├── SEO metadata
└── 設計稿 / 邏輯描述
```

# Commerce & Taiwan Payments

## Base44 內建 Commerce

- Stripe：官方文件確認，可透過 AI chat 安裝
- 支援：product、checkout、payment
- 限制：未見明確的 inventory / order management / coupon 系統文件
- Custom payment provider：需 code，文檔不足

## 台灣金流候選

| 金流 | 信用卡 | ATM | 超商 | LINE Pay | 電子發票 | Sandbox | Node.js SDK | 技術難度 |
|------|--------|-----|------|----------|----------|---------|-------------|----------|
| ECPay | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 公開 | ✅ GitHub 有 | 中 |
| NewebPay | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ 但需另外申請 | ✅ npm | 中 |
| LINE Pay | ✅ | ❌ | ❌ | ✅ | ❌ | ✅ sandbox | ✅ 官方文件 | 中高 |
| Stripe Taiwan | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ test mode | ✅ 官方 | 低（但台灣支付方式有限）|

**結論：**
- Base44 Stripe → 僅適合 Demo / Sandbox，不適合台灣正式上線
- 正式金流：ECPay 或 NewebPay 二選一
- Base44 Serverless Functions 理论上可接 ECPay/NewebPay，但需：
  1. 確認 Base44 Functions 能否設定自訂 header / CORS
  2. 確認能否儲存 Hash Key/IV 等 secrets
  3. 確認 callback webhook 能否被正確接收
  4. 需在 Base44 外另有 production backend，或接受 Functions 繼續跑在 Base44

# Taiwan Food / Ecommerce Requirements

## 烘焙咖啡豆包裝必備標示（查證 2026-08-19）

根據食品安全衛生管理法第 22 條及相關子法：

**強制標示：**
- 品名
- 內容物名稱
- 淨重
- 原產地
- 製造商名稱、地址、電話
- 保存期限 / 有效日期
- 儲存條件
- 食品添加物名稱（如有）

**烘焙咖啡豆特殊規則：**
- 純咖啡豆屬單一成分食品，**得免營養標示**
- 但**不免除上述強制標示**
- 若宣稱「台灣咖啡豆」：必須 100% 台灣種植/採收，否則標示原產地
- 包裝材質需合規（塑膠溶出測試、紙容器無害物質）
- 罰則：$30,000 ~ $3,000,000

**網站頁面應預留：**
- 食品業者登錄號碼
- 商品標示完整內容（等同包裝）
- 退換貨政策
- 隱私權政策
- 聯絡資訊
- 配送說明
- 消費者保護相關

**所有待店家確認的欄位標記為：**
```
PENDING MERCHANT CONFIRMATION
```

# 烘豆廊 Recommended Architecture

```
┌─────────────────────────────────────────┐
│              Day 1-14                   │
│          Base44 Builder                 │
│  ┌─────────────────────────────────┐   │
│  │  Frontend (Base44 runtime)      │   │
│  │  - Homepage / Beans / Finder    │   │
│  │  - Cart / Checkout (Stripe)     │   │
│  │  - About / B2B / Care           │   │
│  └─────────────────────────────────┘   │
│                    ↓                    │
│  ┌─────────────────────────────────┐   │
│  │  Base44 Backend (locked)        │   │
│  │  - Database                     │   │
│  │  - Auth                         │   │
│  │  - Functions                    │   │
│  └─────────────────────────────────┘   │
│                    ↓                    │
│  ┌─────────────────────────────────┐   │
│  │  GitHub (Builder+)              │   │
│  │  - Frontend code backup         │   │
│  │  - Version control              │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│           Day 14+ (Production)          │
│         Migration Target                │
│  ┌─────────────────────────────────┐   │
│  │  Vercel / Cloudflare Pages      │   │
│  │  - Deployed React frontend      │   │
│  │  - From GitHub export           │   │
│  └─────────────────────────────────┘   │
│                    ↓                    │
│  ┌─────────────────────────────────┐   │
│  │  Supabase / Postgres             │   │
│  │  - Database                      │   │
│  │  - Auth                          │   │
│  │  - Storage                       │   │
│  └─────────────────────────────────┘   │
│                    ↓                    │
│  ┌─────────────────────────────────┐   │
│  │  Vercel Functions / Workers     │   │
│  │  - Backend logic                 │   │
│  │  - ECPay/NewebPay integration    │   │
│  └─────────────────────────────────┘   │
│                    ↓                    │
│  ┌─────────────────────────────────┐   │
│  │  ECPay / NewebPay (Production)  │   │
│  │  - 正式金流                      │   │
│  └─────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

# Week 1 Plan

## Day 1：Base44 入門 + 專案建立

**上午：**
- 建立 Base44 account，確認 Free plan 可用
- 建立新 app：「烘豆廊 COFFEE BEANS GALLERY」
- 閱讀 Base44 官方文件：database、auth、 Stripe、GitHub sync
- 確認 Builder+ 功能在免費 trial 或 upgrade 後可使用

**下午：**
- 設計資訊架構：
  - Homepage
  - Beans（商品列表）
  - Product Detail
  - Coffee Finder
  - Cart + Checkout（Stripe sandbox）
  - About / Roaster Story
  - B2B 詢價
  - Customer Care / FAQ
  - Store Info
- 建立 database schema 草稿

** Evening：**
- 建立 GitHub repo 備份機制
- 記錄所有 credits 使用

**產出：** Base44 app skeleton + IA document + DB schema draft

## Day 2：Database + Auth + 首頁

- 建立商品資料表
- 建立用戶 / admin roles
- 實作 Homepage
- 實作 About / Roaster Story
- 連接 custom domain（測試用）

## Day 3：商品系統

- Beans list page
- Product detail page
- 商品 schema 完整欄位
- 圖片上傳到 Base44 Storage
- **Checkpoint：確認 export 可行性，跑一次 GitHub sync**

## Day 4：Coffee Finder

- Rule-based 問卷邏輯
- 4 題篩選
- 資料庫查詢推薦 1-3 款
- 前端互動元件

## Day 5：Cart + Checkout

- Cart 狀態管理
- Stripe Checkout 整合（sandbox）
- Order confirmation
- 訂單資料表

## Day 6：B2B + Customer Care + Store Info

- B2B 詢價表單
- FAQ
- Store information + map
- Instagram / LINE 連結

## Day 7：Mobile QA + Demo 準備

- Mobile responsive QA
- 內容填充（mock data）
- SEO basics
- 錄製 demo video / 截圖
- **GO / NO-GO GATE 檢查**

# Day 7 GO / NO-GO Checklist

- [ ] Homepage 載入正常、mobile 可讀
- [ ] Beans list 可瀏覽、filter 有作用
- [ ] Product detail 顯示完整
- [ ] Coffee Finder 4 題可完成並推薦
- [ ] Cart 加減數量正常
- [ ] Checkout 進入 Stripe sandbox
- [ ] Stripe sandbox 付款成功
- [ ] Order 記錄進 database
- [ ] About / B2B / FAQ / Store Info 都可見
- [ ] Instagram / LINE / Maps 連結正常
- [ ] 商品圖片都顯示
- [ ] SEO title/description 有填
- [ ] Credits 剩餘 > 20%（未燒爆）
- [ ] GitHub sync 成功
- [ ] 整體可說服店家繼續第二週

**若超過 3 項失敗 → NO-GO，停止付費，直接 migration。**

# Week 2 Plan

## Day 8-10：Production Candidate 準備

- 真實商品資料輸入
- Schema finalize
- 移除所有 mock data
- 法務 placeholder 頁面
- SEO complete

## Day 11-12：金流 PoC

- Stripe sandbox 完整測試
- 評估 ECPay/NewebPay 接法
- 決定 production 金流策略

## Day 13：GitHub + Export + Backup

- 確認 GitHub repo 有完整 frontend code
- 嘗試 local development（npm install + npm run dev）
- 確認 export 是否仍依賴 Base44 SDK
- 完整 backup

## Day 14：QA + Documentation + Handoff

- 全面 QA
- 撰寫 deployment 文件
- Export validation
- 製作 migration guide
- **禁止新增功能**

# Day 14 Definition of Done

- [ ] 所有功能 tested
- [ ] GitHub repo 有完整 commit history
- [ ] Export 已驗證（local run 或 documented dependency）
- [ ] Database schema documented
- [ ] SEO 完成
- [ ] Legal placeholders 完成
- [ ] Backup 存在多處
- [ ] Migration guide 撰寫完成
- [ ] 店家可接收並理解網站操作
- [ ] 正式 hosting + 金流方案已定案

# Escape Plan

## Day 3 Escape（Builder plan 已付費）

**保留：**
- Base44 app 截圖 + demo
- 商品資料表結構
- Coffee Finder 邏輯
- UI design 方向

**匯出：**
- GitHub repo（frontend code）
- Database schema（手動記錄）
- 商品圖片（從 Base44 Storage 下載）

**下一站：**
- Lovable（Supabase backend，GitHub 雙向 sync）
- 或 v0 + Supabase 手動整合

## Day 7 Escape（Demo 失敗）

**保留：**
- 研究結論
- IA + schema
- Coffee Finder logic

**匯出：**
- 截圖 + 文件
- GitHub repo（如有）

**下一站：**
- 評估是否改用其他 AI builder
- 或放棄 builder 工具，改傳統開發

## Day 14 Escape（Base44 確認不可行）

**保留：**
- 完整 GitHub frontend code
- Database schema + mock data
- 設計系統 / component 結構
- 商品資料 + 圖片

**匯出：**
- GitHub repo
- Base44 Storage 下載所有圖片
- Manual database export（如有匯出功能）

**程式重建：**
- React + Vercel/Cloudflare Pages
- Supabase（DB + Auth + Storage）
- ECPay/NewebPay Node.js integration
- 預估重建成本：2-4 週

**下一站推薦：**
- Frontend：Vercel + Next.js 或 Cloudflare Pages + React
- Backend：Supabase 或自行 Postgres
- 金流：ECPay 或 NewebPay
- 優先保留可攜帶的 assets：UI components、logic、content

# Risk Register

| Risk | Probability | Impact | Mitigation | When to test |
|------|------------|--------|------------|--------------|
| Base44 export 無法離開 SDK | High | High | Day 3 跑 local dev test | Day 3 |
| Credits 燒太快 | Medium | Medium | 每日追蹤 credits，Free→Builder 跳級 | Day 1-7 |
| Stripe 不適合台灣 | High | High | Day 7 確認金流策略 | Day 7 |
| 食品標示合規問題 | Medium | High | Day 1 列出 checklist 給店家 | Day 1 |
| Base44 iOS App 與 web 不同步 | Medium | Low | 確認 web 版功能完整 | Day 1 |
| GitHub sync 永久綁定 | Medium | Medium | 用 test repo 先試 sync | Day 2 |
| Cloudflare/Tunnel 額外成本 | Low | Low | 確認 Base44 hosting 是否夠用 | Day 7 |
| 店家 Day 7 不满意 | Low | High | Day 7 demo 前先內部 review | Day 7 |

# Source Conflicts

## CONFLICT 1：Base44 是否真的「you own your apps」

- **Source A（官方）**：base44.com/pricing FAQ：「Yes. You own everything you build on Base44: your code, your data, your users.」
- **Source B（Reddit / escapebase44.com / blink.new）**：Export 出來的是 bare React/Vite app，仍依賴 @base44/sdk；backend/auth/storage 全部鎖在平台
- **建議**：Week 1 Day 3 實測 export → local dev，親自驗證依賴程度

## CONFLICT 2：GitHub sync 能否 disconnect

- **Source A（官方 docs）**：可 disconnect，但無法 reconnect 到同一 repo
- **Source B（社群）**：sync 是永久性的，version history 丟失
- **建議**：用 test repo 實驗，不要直接用 production repo

## CONFLICT 3：Base44 後端能否 externally deploy

- **Source A（官方）**：強調可 export
- **Source B（webtwizz.com / blink.new）**：Base44 不生成標準 Vite/Next.js，後端鎖在 Base44 runtime
- **建議**：接受 Base44 只能當 prototyping + demo 平台，production 必須 migration

# Unknowns Requiring Merchant Confirmation

1. PENDING MERCHANT CONFIRMATION：公司名稱 / 統一編號
2. PENDING MERCHANT CONFIRMATION：食品業者登錄號碼
3. PENDING MERCHANT CONFIRMATION：咖啡豆原產地明細
4. PENDING MERCHANT CONFIRMATION：製造商地址 / 電話
5. PENDING MERCHANT CONFIRMATION：保存期限建議
6. PENDING MERCHANT CONFIRMATION：Logo / 品牌素材
7. PENDING MERCHANT CONFIRMATION：商品價格
8. PENDING MERCHANT CONFIRMATION：B2B 詢價流程
9. PENDING MERCHANT CONFIRMATION：店址 / 營業時間
10. PENDING MERCHANT CONFIRMATION：是否需電子發票
11. PENDING MERCHANT CONFIRMATION：物流合作對象
12. PENDING MERCHANT CONFIRMATION：Instagram / LINE 帳號

# Final Recommendation

1. **Base44 的角色**：14 天內的 demo + prototype 平台，不是 production
2. **GitHub 的角色**：從 Day 1 就開，作為 code 主權備份；但清楚知道 export 後仍需 migration
3. **最終 production hosting**：Vercel 或 Cloudflare Pages + Supabase
4. **Backend 是否留下 Base44**：否，正式上線前必須 migration
5. **金流建議**：Demo 用 Stripe sandbox；Production 用 ECPay 或 NewebPay
6. **Day 1 第一件事**：建立 account → 開 GitHub repo → 確認 Free plan 可做出首頁
7. **Day 3 checkpoint**：跑一次 GitHub sync + local dev test，確認 export 依賴
8. **Day 7 decision**：Demo 夠好 + credits 可控 + GitHub sync 成功 → GO；否則 NO-GO
9. **Day 14 exit**：Export validated + backup complete + migration guide written
10. **是否值得付第二週**：只在 Day 7 通過且願意接受 migration 計畫時付 Builder plan
