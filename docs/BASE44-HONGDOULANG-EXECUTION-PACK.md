# BASE44 烘豆廊 Execution Pack

直接交給 Base44 執行的施工包。所有 prompt 可直接複製貼上。

---

## 1. Project Brief

```
Build a coffee bean e-commerce website for "烘豆廊 COFFEE BEANS GALLERY" located in Hualien, Taiwan.

Business:
- Specialty coffee roasting
- Retail coffee bean sales
- B2B commercial beans
- Physical store with beverages
- Future online store

Tech: Base44 Builder plan
Payment: Stripe sandbox for demo; ECPay/NewebPay for production later
GitHub: Required from Day 1
Export: Required by Day 14

Do NOT fabricate any business registration, food license, insurance, or company info. Use placeholders marked PENDING MERCHANT CONFIRMATION.
```

---

## 2. Brand Direction

```
Brand: 烘豆廊 COFFEE BEANS GALLERY
Location: Hualien, Taiwan
Style: Warm, artisanal, minimal, specialty coffee aesthetic
Colors: Earth tones, deep browns, cream, with accent color TBD
Typography: Clean, readable, Asian-friendly
Imagery: Coffee beans, roasting process, Hualien landscape, hands-on craft
Tone: Professional but approachable, knowledgeable but not snobby
```

---

## 3. Information Architecture

```
/
├── Homepage
├── Beans (product catalog)
│   └── [slug] (product detail)
├── Coffee Finder (recommendation quiz)
├── About / Roaster Story
├── B2B (commercial inquiry)
├── Customer Care / FAQ
├── Store (location, hours, contact)
└── Legal
    ├── Privacy
    ├── Terms
    └── Shipping / Return
```

---

## 4. Product Schema

```
Create a "coffees" table with these fields:

name: string (e.g., "花蓮厭氧蜜處理")
slug: string (auto-generated from name)
price: number (TWD)
weight: number (grams, e.g., 200)
stock: number
origin: string
country: string
region: string
farm: string
producer: string
variety: string
altitude: string
process: string (washed / natural / honey / anaerobic...)
roast_level: string (light / medium / medium-dark / dark)
flavor_notes: array (e.g., ["花香", "柑橘", "蜂蜜"])
acidity: number (1-5)
sweetness: number (1-5)
body: number (1-5)
bitterness: number (1-5)
brew_methods: array (e.g., ["手沖", "義式", "法壓"])
grind_options: array (e.g., ["全豆", "粗 grind", "中 grind", "細 grind"])
roast_date: date
rest_days: number
description: text
images: array of URLs
featured: boolean
availability: boolean
```

---

## 5. Demo Data Rules

```
Add 6-8 demo coffee products:

1. 花蓮厭氧蜜處理 - 淺焙 - 花香/柑橘/蜂蜜
2. 阿里山山茶 - 中焙 - 堅果/巧克力/焦糖
3. 耶加雪菲水洗 - 淺焙 - 水果/花香/茶感
4. 曼特寧濕刨法 - 深焙 - 草本/黑巧克力/煙燻
5. 巴拿馬瑰夏 - 極淺焙 - 茉莉/橙花/蜂蜜
6. 巴西喜拉多 - 中焙 - 堅果/牛奶巧克力/焦糖

Use placeholder images from unsplash or similar.
All prices in TWD.
All origins verified - do NOT claim Taiwan origin for non-Taiwan beans.

For B2B section, add placeholder inquiry form.
For store info, use placeholder address in Hualien.
```

---

## 6. Component Map

```
Components to build:
- Navbar (sticky, responsive)
- Hero (full-width image + headline)
- ProductCard (image, name, price, quick view)
- ProductGrid (filterable grid)
- ProductDetail (full info, add to cart)
- FlavorFilter (acidity/body/bitterness sliders)
- CoffeeFinder (4-step quiz)
- Cart (slide-out or page)
- Checkout (Stripe integration)
- Footer (links, social, legal)
- About (story, photos)
- B2BForm (inquiry form)
- FAQ (accordion)
- StoreInfo (map, hours, contact)
```

---

## 7. Page Requirements

### Homepage
- Hero section with brand name + tagline
- Featured products (3-4)
- Coffee Finder CTA
- About teaser
- Store info snippet

### Beans List
- Filter by roast level, origin, flavor
- Search by name
- Sort by price / roast date / featured
- Responsive grid

### Product Detail
- Image gallery
- Full specs (origin, farm, altitude, process, roast, flavor notes)
- Brew method suggestions
- Grind options selector
- Add to cart with quantity
- Related products

### Coffee Finder
- 4 questions:
  1. 怕不怕酸？(Acidity tolerance)
  2. 使用什麼沖煮方法？(Brew method)
  3. 偏好風味？(花香/水果/巧克力/堅果/濃郁)
  4. 喜歡清爽還是厚實？(Body preference)
- Result: show 1-3 recommended coffees

### Cart + Checkout
- Cart with quantity controls
- Stripe Checkout (sandbox)
- Order confirmation page
- Order saved to database

### About / Roaster Story
- Brand story
- Roasting philosophy
- Team / process photos (placeholder)

### B2B
- Inquiry form (name, company, email, volume, message)
- Save to database
- Email notification (optional)

### Customer Care / FAQ
- Accordion FAQ
- Contact form
- Shipping info placeholder
- Return policy placeholder

### Store
- Address (PENDING MERCHANT CONFIRMATION)
- Hours (PENDING MERCHANT CONFIRMATION)
- Phone (PENDING MERCHANT CONFIRMATION)
- Google Maps embed
- Instagram link
- LINE link

---

## 8. Coffee Finder Logic

```
Rule-based recommendation (v1):

Step 1: Acidity
- 怕酸 → filter acidity <= 2
- 還好 → no filter
- 喜歡酸 → filter acidity >= 4

Step 2: Brew method
- 手沖 → filter brew_methods includes "手沖"
- 義式 → filter roast_level != "light"
- 法壓 / 浸泡 → no filter
- 其他 → no filter

Step 3: Flavor preference
- 花香 → filter flavor_notes includes "花香"
- 水果 → filter flavor_notes includes "水果"
- 巧克力 → filter flavor_notes includes "巧克力"
- 堅果 → filter flavor_notes includes "堅果"
- 濃郁 → filter roast_level in ["medium-dark", "dark"] OR body >= 4

Step 4: Body preference
- 清爽 → filter body <= 2
- 厚實 → filter body >= 4
- 都可以 → no filter

After all filters: sort by featured DESC, limit 3 results.
If no results: show 3 featured coffees with message "你可能也喜歡..."
```

---

## 9. Commerce Flow

```
1. User browses Beans list
2. User clicks Product Detail
3. User selects grind option + quantity
4. "Add to Cart" → cart state updated
5. User clicks Cart icon
6. Review cart → click "Checkout"
7. Stripe Checkout Session created (sandbox mode)
8. User redirected to Stripe hosted checkout
9. Payment succeeds → webhook → order saved
10. Order confirmation page shown
11. (Optional) Confirmation email

Database tables needed:
- orders (id, user_id, items, total, status, created_at)
- order_items (id, order_id, product_id, quantity, price)
```

---

## 10. Customer Care Structure

```
FAQ Categories:
- 購買相關（運費、付款、配送）
- 咖啡知識（烘焙度、風味、沖煮）
- 退換貨
- 會員/帳號

Contact Form:
- Name
- Email
- Category (dropdown)
- Message
- Save to database

Response time SLA placeholder: "我們會在 2 個工作日內回覆"
```

---

## 11. B2B Structure

```
Inquiry Form Fields:
- 公司名稱
- 聯絡人
- email
- 電話
- 預計採購量
- 需求描述
- 用途（咖啡店 / 餐廳 / 办公室...）

Save to "b2b_inquiries" table.
Admin notification: email (placeholder)

Page content:
- 商用豆說明
- 最低訂購量 (PENDING MERCHANT CONFIRMATION)
- 配送說明
- 聯絡方式
```

---

## 12. Mobile Requirements

- All pages responsive
- Touch-friendly buttons (min 44px)
- Cart accessible from any page
- Checkout flow mobile-optimized
- Images lazy-loaded
- Font size readable on mobile
- No horizontal scroll

---

## 13. SEO Requirements

- Page titles: "烘豆廊 COFFEE BEANS GALLERY | [Page]"
- Meta descriptions per page
- Open Graph tags for social sharing
- Structured data for products (JSON-LD)
- Alt text for all images
- Sitemap (check if Base44 supports)
- robots.txt (check if Base44 supports)

---

## 14. Legal Placeholders

```
Pages to create with placeholders:

/privacy
- Privacy policy placeholder
- Mark all merchant-specific fields as PENDING MERCHANT CONFIRMATION

/terms
- Terms of service placeholder

/shipping
- Shipping policy placeholder
- Delivery areas (PENDING MERCHANT CONFIRMATION)
- Shipping fees (PENDING MERCHANT CONFIRMATION)
- Delivery time estimates

/returns
- Return policy placeholder
- 7-day return rule (to be confirmed)

Food-related (on product pages / footer):
- 食品業者登錄：PENDING MERCHANT CONFIRMATION
- 食品標示：see schema above
- 責任保險：PENDING MERCHANT CONFIRMATION
```

---

## 15. Do-not-fabricate Rules

**NEVER create:**
- Fake company registration number
- Fake food business license
- Fake insurance policy
- Fake certifications
- Fake reviews or ratings
- Fake store hours or address
- Fake contact information
- Fake pricing that doesn't match merchant's intent

**ALWAYS use:**
- "PENDING MERCHANT CONFIRMATION" for all merchant-provided data
- Placeholder text that is clearly marked as placeholder
- Realistic but fictional demo data only for product catalog

---

## 16. GitHub / Portability Rules

```
Day 1:
- Create GitHub repo: hongdoulang-coffee (or merchant's choice)
- Connect Base44 → GitHub 2-way sync
- Use test repo first if possible

Day 3:
- Test local development: clone → npm install → npm run dev
- Document any Base44 SDK dependencies
- Commit export test results

Day 7:
- Verify GitHub has latest code
- Backup all Base44 Storage images to local

Day 14:
- Final GitHub sync
- Complete export validation
- Document migration requirements
- All assets backed up externally
```

---

## 17. Day 1 Master Prompt

```
Create a new Base44 app called "烘豆廊 COFFEE BEANS GALLERY".

1. Set up the database schema for coffee products (see schema below).
2. Create the basic page structure: Homepage, Beans, Coffee Finder, About, B2B, Customer Care, Store.
3. Build a beautiful Homepage with hero section, featured products teaser, and navigation.
4. Connect GitHub repo "hongdoulang-coffee" for 2-way sync.
5. Use warm, artisanal coffee shop aesthetic.
6. Make it fully responsive for mobile.

Database schema:
[name, slug, price, weight, stock, origin, country, region, farm, producer, variety, altitude, process, roast_level, flavor_notes, acidity, sweetness, body, bitterness, brew_methods, grind_options, roast_date, rest_days, description, images, featured, availability]

DO NOT add fake merchant info. Use placeholders.
DO NOT enable Stripe yet - just create the UI structure.
```

---

## 18. Build Prompt Queue

### Prompt 2: Database + Admin

```
Create a "coffees" table with all product fields.
Create an admin view to add/edit/delete coffees.
Create a "b2b_inquiries" table with: company, contact, email, phone, volume, message, created_at.
Create an admin view for B2B inquiries.
```

### Prompt 3: Beans List Page

```
Build the Beans list page:
- Filter sidebar: roast_level, origin, flavor notes
- Search bar: search by name
- Sort: price, roast_date, featured
- Product cards in responsive grid
- Click card → Product Detail page
Use demo data (6 products).
```

### Prompt 4: Product Detail

```
Build Product Detail page:
- Image gallery (main + thumbnails)
- All product specs displayed nicely
- Grind options selector
- Quantity selector
- "Add to Cart" button
- Related products section
- Breadcrumb navigation
```

### Prompt 5: Coffee Finder

```
Build a 4-step Coffee Finder quiz:
Q1: 怕不怕酸？(完全不能 / 還好 / 喜歡酸)
Q2: 使用什麼沖煮方法？(手沖 / 義式 / 法壓 / 其他)
Q3: 偏好風味？(花香 / 水果 / 巧克力 / 堅果 / 濃郁)
Q4: 喜歡清爽還是厚實？(清爽 / 厚實 / 都可以)

After answers: show 1-3 recommended coffees from database.
Use rule-based logic (not AI).
Show reasoning: "因為你選擇了..."
```

### Prompt 6: Cart + Checkout

```
Build Cart and Checkout:
- Cart state management (add/remove/quantity)
- Cart icon in navbar with count badge
- Cart page with item list + total
- Checkout button → Stripe Checkout (sandbox mode, use test keys)
- Order confirmation page
- Save order to "orders" table
- Stripe webhook handler (placeholder)
```

### Prompt 7: About + B2B + Store

```
Build remaining pages:
- About: brand story, roasting philosophy, placeholder images
- B2B: inquiry form → save to b2b_inquiries table
- Store: placeholder map, hours (PENDING), phone (PENDING), Instagram/LINE links
- Customer Care: FAQ accordion, contact form
```

---

## 19. QA Prompt

```
Run QA on all pages:
1. Check all links work
2. Check images load
3. Check mobile layout on iPhone SE / iPhone 15 / iPad
4. Check cart flow: add → view → checkout → confirm
5. Check Coffee Finder: all 4 questions → results
6. Check B2B form submits
7. Check all PENDING MERCHANT CONFIRMATION placeholders are visible
8. Check SEO: title, description, OG tags on each page
9. Check no fake data in final pages
10. Check Stripe is in test mode
```

---

## 20. Export / Handoff Prompt

```
Prepare for export:
1. Final GitHub sync
2. Download all images from Base44 Storage
3. Export all database data as CSV/JSON
4. Document:
   - Current features
   - Known limitations
   - Base44 SDK dependencies
   - Migration requirements
   - Taiwan payment integration plan
5. Create MIGRATION.md with:
   - What needs to be rebuilt
   - Recommended stack (Vercel + Supabase + ECPay)
   - Estimated effort
```

---

## Appendix: Base44 Settings Checklist

```
[ ] Account created
[ ] App created: "烘豆廊 COFFEE BEANS GALLERY"
[ ] GitHub repo connected
[ ] Database tables created
[ ] Auth configured (email/password)
[ ] Stripe connected (sandbox keys)
[ ] Custom domain configured (if needed)
[ ] Analytics enabled
[ ] Environment variables set
[ ] Version history enabled
```

## Appendix: Credits Budget

```
Week 1 estimate:
- Free plan: 25 message credits + 100 integration credits
- Expected usage: ~150-200 messages for full build
- Plan to upgrade to Builder ($50/mo) by Day 3-5
- Builder gives: 250 messages + 10,000 integrations

Daily tracking:
- Track messages used vs remaining
- If < 20% remaining mid-day, reduce AI chat usage
- Switch to manual code editing to save credits
```

## Appendix: Taiwan Compliance Checklist

```
[ ] 食品業者登錄號碼 (PENDING)
[ ] 商品標示審核 (PENDING)
[ ] 包裝標示設計 (PENDING)
[ ] 責任保險 (PENDING)
[ ] 隱私權政策 (lawyer review recommended)
[ ] 退換貨政策
[ ] 消費者保護
[ ] 電子發票 (if needed)
[ ] 營業登記 (PENDING)
```
