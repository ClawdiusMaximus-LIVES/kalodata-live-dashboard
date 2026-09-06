# ~/kalodata — QVC Opportunity System + TikTok LIVE Performance

This repo now serves **two linked missions** for Mike, a TikTok Shop **affiliate
creator** (not a seller), DreamSeeds brand, solo indie iOS dev. He streams TikTok
Shop LIVE from TikTok LIVE Studio on a MacBook Pro and also makes pre-recorded /
paid UGC videos. **This month is make-or-break: the priority is generating as much
money as fast as possible from LIVE to save the ship.**

1. **QVC Opportunity finder** (original) — find "profitable low-hanging fruit":
   products that are actually selling but have very few creators promoting them.
   Validated: Bose QuietComfort earbuds, only 2 creators (~$110/creator/wk) → made
   a video → instant traction.
2. **TikTok LIVE Performance system** (new, Sept 2026) — turn the dashboard into
   Mike's LIVE analytics cockpit: read the funnel in real time, know when to end a
   stream, and drive decisions from HIS own numbers after ~10 streams. Product mix
   on lives: Euhomy coolers/car fridges, KAER + biometric safes, SKIL power-tool
   launch parties, Bose, Bluetti, multi-position ladder. QVC ships a lot of samples.

## Files (all in ~/kalodata/)

- `dashboard.py` — stdlib-only web UI, port 8787 (phone:
  http://mac-studio.local:8787). **Deployed & always-on at
  https://kalodata-production.up.railway.app** (Railway project/service `kalodata`,
  workspace "clawdiusmaximus-lives's Projects"; logged in as dreamseedsapp@gmail.com).
  Tabs today: Shop Scanner (paginated rank + revenue band + launch-date filter +
  Card $ / Ad % proxy columns + one-click presets + all-shops mode + CSV/cache
  export + cost guard), Product Lookup (keyword search, per-product stat card,
  bulk creator-count loading, cross-shop "Gem Hunt"), Livestreams (Kalodata
  `/livestream/rank` scanner — see below).
  Run: `python3 ~/kalodata/dashboard.py`. If "Address already in use":
  `kill $(lsof -ti :8787)` first.
- `kalodata_qvc.py` — CLI/cron scanner. Outputs qvc_opportunities_DATE_Nd.csv.
  Suggested cron: `0 6 * * * /usr/bin/python3 ~/kalodata/kalodata_qvc.py`
- `cache.db` — SQLite, SHARED by both scripts (on Railway: /data volume, seeded
  once from bundled cache.db). Tables: details(product_id PK, fetched_at,
  creator_count, video_count, live_count, date_range, raw JSON), 7-day TTL,
  window-aware (cache HIT only if same date_range); rank_history(run_date,
  product_id, rank, units, revenue); saved_shops.
- `LIVE_PLAYBOOK.md` — current best-practice doc for reading LIVE analytics &
  when to end. **Keep it updated; re-render `LIVE_PLAYBOOK.pdf` whenever it
  changes** (Chrome headless: `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  --headless=new --no-pdf-header-footer --print-to-pdf=out.pdf file://$PWD/x.html`
  — no pandoc/wkhtmltopdf installed). Camera-side PDFs already generated:
  `LIVE_PLAYBOOK.pdf`, `LIVE_pre_stream_checklist.pdf`, `LIVE_checkin_card.pdf`
  (regenerate when the playbook changes). Fill the "My numbers" section from his
  real stream log as data comes in.
- `LIVE_LOG_SPEC.md` — spec for the LIVE section. **BUILT** into dashboard.py as
  the "🔴 LIVE Log" tab (Sept 2026): `live_stream` + `live_checkin` tables,
  endpoints `/api/live/{list,save,get,delete,checkin,trends,import}`, SPA views
  (list / new+edit form / detail with STAY·SWAP·END decision badge + phase + 15-min
  check-in form + timeline + bar charts / trends by hour·weekday·product / Creator
  Live Performance CSV import with alias-mapped headers). Distinct from the Kalodata
  livestream *scanner* tab ("Livestreams") which reads OTHER creators' streams. Live
  log uses NO Kalodata credits. Backend logic covered by an offline test
  (scratchpad/test_live.py pattern).
- `HANDOFF.md` — session handoff (dashboard deploy + Ranger Tales sprint). Read on restart.

## TikTok LIVE Performance — the mission (from CLAUDEnew.md, Sept 2026)

Three workstreams, in priority order for "save the ship":
1. **Live log** — implement `LIVE_LOG_SPEC.md`: `live_stream` + `live_checkin`
   tables in the shared SQLite; routes `/live`, `/live/new`, `/live/<id>`,
   check-in POST, `/live/trends`, `/live/import` (Creator Live Performance CSV —
   header names unknown, print header first then map). In-stream decision badge:
   STAY / SWAP-or-CHANGE-FORMAT / END-ON-A-HIGH from the last 3 check-ins, plus
   phase label (0–15 Active push, 15–60 Learning, 60+ Adapting). Phone-friendly
   (iPad check-in form = one screen, one tap). **DONE** — implemented as the LIVE
   Log tab + `/api/live/*` endpoints (SPA pattern, not separate pages); scanner
   routes untouched. Deploy to Railway with `railway up` when ready.
2. **Playbook** — keep `LIVE_PLAYBOOK.md` current + render PDFs (playbook,
   pre-stream checklist, 15-min check-in card).
3. **Research** — web-search to improve the playbook: (a) real published data on
   live length vs GMV for affiliates, (b) LIVE Board / Creator Live Performance
   export field definitions, (c) time-slot & day-of-week patterns for
   home/electronics/tools, (d) what top US tools/electronics affiliates do
   structurally (segment length, flash-deal cadence, giveaway timing). Cite
   sources; distinguish TikTok-official from agency-blog claims.

Where LIVE data lives (no Kalodata credits needed — it's Mike's own TikTok data):
- **During stream:** TikTok Shop Creator site → LIVE Manager → monitor icon → LIVE
  Board (traffic, engagement, sales, product perf, violations). LIVE Board open on
  iPad beside LIVE Studio on the Mac.
- **After:** Analytics → LIVE Analytics → All LIVE videos; export "Creator Live
  Performance" CSV → feed `/live/import`.

## Kalodata Open API (reverse-engineered; powers the QVC/opportunity tabs)

- Base: `https://www.kalodata.com/openapi/v1`
- Auth: header `X-API-Key: <key>` — key in `~/.config/kalodata/env` as
  `KALODATA_API_KEY=...` (UUID). On Railway set via `railway variables
  --set-from-stdin`. **NEVER print or commit the key.**
- Endpoints (all POST, JSON body): `/product/rank`, `/product/detail`,
  `/shop/rank`, `/livestream/rank` + `/livestream/detail` (VERIFIED).
  category/creator/video rank+detail also exist per module (untested).
- Required body params: `region` ("US"), `language` (**"en-US"**, NOT "en" —
  allowed: en-US, pt-BR, ko-KR, id-ID, es-ES, fr-FR, zh-CN, vi-VN, ja-JP, th-TH),
  `currency` ("USD"), `date_range` ("lastDay"|"last7Day"|"last30Day"; detail also
  last90Day/180/365).
- Optional rank params: `shop_id`, `keyword`, `page`, `page_size` (100 max),
  `launch_date` ("<3"|"<7"|">30" style).
- GOTCHA: `sort_field` is a Jackson object (SortFieldReq), NOT a string — passing
  "sales_volumn" 500s. Omit it; default order ≈ revenue desc.
- Rank row fields: product_id, product_name, revenue, commission_rate (percent
  number, e.g. 18.0), revenue_growth_rate, sales_volumn (sic), unit_price,
  live_revenue, video_revenue, showcase_revenue, launch_date.
- Detail fields add: creator_number, video_number, live_number, min_price,
  max_price, product_shop_id, pri/sec/ter_cate_id, product_review_count.
- Errors: {"success":false,"message":...,"code":"501"} — validation messages are
  descriptive; use them to discover params. Validation errors appear free.
- Billing: rank = 0.1 credit × ceil(rows/100); detail = 0.1 credit/call.
  1 credit ≈ $0.10, so ~1¢/call. **Cost guard in dashboard.py:** any scan whose
  NEW (uncached) detail spend > $0.25 returns needs_confirm + a client dialog.
- QVC shop_id: `7495811038271212487` ("QVC, Inc").
- Livestream module (VERIFIED 2026-08 — the dashboard "Livestreams" tab):
  `/livestream/rank` + `/livestream/detail`. Same required params; `page_size`
  must be **>=10** (3 → "Invalid Parameter"); `sort_field` same SortFieldReq —
  omit. `shop_id` filters to livestreams that SOLD that shop's products; `keyword`
  works too. Rank fields: livestream_id, livestream_title, creator_handle,
  creator_id, livestream_start_time/end_time (epoch ms), livestream_duration
  (sec), revenue, unit_price, views, record_type. GOTCHA: the `page` param
  REPEATS the same page — dedupe by livestream_id (stop when a page adds nothing
  new). Detail adds: product_number, viewers, gpm, top3_product_ids.
  `rank`+shop_id = SHOP-ATTRIBUTED revenue; `detail` = WHOLE-cart total → a
  "% QVC of cart" column separates real promoters from cart-padders (pending).
  QVC's own accounts to filter for affiliates-only: qvc, qvcbeauty, qvcfashion, qvchome.
- **Paid plan being cancelled — run on API credits only.** If calls return
  auth/"Insufficient credit balance" errors, recharge credits (cheapest re-sub is
  the fix if the key itself dies). LIVE-performance work needs NO Kalodata credits.

## QVC scoring model

opportunity = commission $/creator = (revenue × commission_rate/100) /
creator_number. Filters: min units floor (kills dead overpriced inventory),
revenue band $1k–$25k for "gem hunting" the mid-tail. Ad % proxy = (revenue −
video_rev − live_rev − showcase_rev)/revenue → upper bound on GMV-Max ad share
(>60% ≈ heavily ad-pushed).

## Deploy / verify discipline (bit us twice — do not skip)

- Deploy: `cd ~/kalodata && railway up --detach --service kalodata` (tars the dir,
  no git). Builds SLOW (~5–7 min). Confirm swap by polling the URL for a marker.
- After ANY change: `python3 -c "import ast; ast.parse(open('dashboard.py').read())"`.
- After ANY JS/HTML change (PAGE is a Python string!): extract the `<script>` and
  `node --check`. Python string-escaping eats `\n`/`\'` → silently breaks page JS.
  Write `\\n` / reword to avoid apostrophes.
- For logic, write an offline mocked test (no credits).

## Working style

Direct, results-oriented, minimal back-and-forth. Copy-paste-ready commands.
Proceed on reasonable assumptions; state them in one line. Not a coder — explain
in plain terms, automate everything, **verify patches before claiming success**
(previous sessions had silent patch failures; assert on needle counts / test after
editing). Often on iPhone/iPad — keep UI phone-width friendly. Voice-to-text →
parse intent (homophones). Exhausted/broke — SUBTRACT work, action over
explanation, one recommendation not 12 options. Human checkpoints only where
necessary. **Compliance: never put prices or competitor brand names in anything
that could appear on camera; no external links/QR on screen while live.**

## Roadmap ideas Mike has raised (QVC side)

- Weekly "new QVC listings" sweep (launched <7d, min units 1) → cron + notification.
- Better GMV-Max spend detection (Ad % is a proxy; his authorized dashboards = truth).
- More shops beyond QVC; category-rank hunting; momentum from rank_history;
  auto-alerts when creator count still low but revenue accelerating.
