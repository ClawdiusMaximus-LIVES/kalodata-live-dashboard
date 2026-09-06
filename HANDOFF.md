# Session Handoff — QVC Dashboard + Ranger Tales sprint

_Last updated: 2026-08-21. Read this first on restart, then CLAUDE.md._

---

## PART 1 — QVC Opportunity Dashboard (this project, `~/kalodata/`)

### What it is / where it runs
- `dashboard.py` — stdlib-only web UI. **Deployed & always-on at
  https://kalodata-production.up.railway.app** (Railway project `kalodata`,
  service `kalodata`, workspace "clawdiusmaximus-lives's Projects"). Also runs
  locally: `python3 ~/kalodata/dashboard.py` → localhost:8787.
- **NOT on Vercel** — it's one Python process (UI+API+SQLite); Vercel serverless
  can't do the SQLite cache/threads. See [[project_kalodata_remote_hosting]].

### Deploy
- `cd ~/kalodata && railway up --detach --service kalodata` (already logged in as
  dreamseedsapp@gmail.com; no git needed — it tars the dir). Builds are SLOW this
  season (~5–7 min). Confirm swap by polling the URL for a marker string or
  `POST /api/cache`. Setting a Railway variable ALSO triggers a redeploy from the
  last-uploaded source (can race with `railway up`).
- Config via env (falls back to local file so localhost still works):
  `KALODATA_API_KEY` (set on Railway via `railway variables --set-from-stdin`,
  never printed), `PORT` (Railway injects), `KALO_DATA_DIR=/data` (the Railway
  **volume** `kalodata-volume` — persists cache across redeploys),
  `DASHBOARD_PASSWORD` (optional Basic Auth; currently NONE — Mike chose no gate).
- Cache: `cache.db`. On Railway it lives on the /data volume; `seed_cache_if_needed()`
  seeds it once from the deploy-bundled cache.db when the `details` table is empty.

### VERIFY DISCIPLINE (bit us twice — do not skip)
- After ANY change: `python3 -c "import ast; ast.parse(open('dashboard.py').read())"`.
- After ANY JS/HTML change (PAGE is a Python string!): extract the `<script>` and
  run `node --check`. Python string-escaping **eats `\n` and `\'`** → silently
  breaks the whole page's JS (killed the Product Lookup tab once, the Remove-shop
  alert once). Write `\\n` / reword to avoid apostrophes.
- For logic, write an offline mocked test (no credits) — see how the cost-gate and
  window-cache were verified.

### Features built this session (all live)
- **One-click presets** (Shop Scanner): New this week / New this month /
  Low-creator gems / **Fewest videos** / **Fewest videos (deep = 500)** / Fewest creators.
- **All-shops mode** (`shop_id="ALL"` → no shop filter = global rank).
- **Parallel detail fetch** (ThreadPoolExecutor, 8 workers) — keeps deep scans
  under Cloudflare/Railway ~100s request limit.
- **CSV export** (client-side, 0 credits) + **Cache export** (`/api/cache`, reads
  local cache, 0 credits, works at $0 balance).
- **Cost guard**: any scan whose NEW (uncached) detail spend > $0.25 returns
  `{needs_confirm, estimate, n_new, n_cached}` and the client shows a dialog
  (leads with credits, then $) before spending. Cached products are free + excluded.
- **Window-aware detail cache** (FIXED the 7-day-vs-30-day bug): `details` table
  gained a `date_range` column; cache HIT only if same window. Migration auto-adds
  the column to old DBs.
- **Saved shops** (persistent): `saved_shops` table + `/api/save_shop`,
  `/api/saved_shops`, `/api/remove_shop`. Find-a-shop now saves permanently; "✕
  Remove shop" button removes. Populates all 3 shop dropdowns.
- **Livestreams tab**: `/livestream/rank` + `shop_id` = livestreams that SOLD that
  shop's products, ranked by revenue, deduped by livestream_id (their `page`
  param repeats!). "Hide the shop's own accounts" checkbox filters handles
  containing the shop's name token (qvc/qvcbeauty/qvcfashion/qvchome). Creator
  handle links to their TikTok. Full livestream API spec is now in CLAUDE.md.

### Billing reality
- ~1 credit ≈ $0.10; detail = 0.1 credit ≈ 1¢; rank = 0.1 credit / 100 rows.
- Mike runs on Kalodata credits (cancelled/plans to cancel web sub). If calls return
  "Insufficient credit balance" he must recharge. Validation errors are free.

### OPEN / NEXT (dashboard)
- **PENDING — Mike hasn't answered:** add a **"% QVC of cart"** column to the
  Livestreams tab. Finding (verified): `livestream/rank`+shop_id gives the
  SHOP-ATTRIBUTED revenue (actual QVC sales), but `livestream/detail` gives the
  WHOLE-cart total. Showing `QVC$ / total$` separates real QVC promoters
  (@likeag6but10 ~84%) from cart-padders (@monchodeals ~12% of a $21k/97-product
  cart). Costs ~1¢/live → make it an optional "Load cart %" button so normal runs
  stay cheap.
- Custom domain not attached (Railway app domain only) — `railway domain <custom>`
  + a CNAME if wanted.

---

## PART 2 — Ranger Tales cash-flow sprint (the REAL business; separate repos)

Mike is in an acute cash crunch (broke, car, rent) and streaming TikTok Shop to
survive, but the goal is **Ranger Tales** (his GPS audio-tour business). Full
context: [[project_ranger_tales_cashflow_sprint]]. Source of truth lives in
`~/Documents/Claude/Projects/Ranger Tales Strategy/` (CLAUDE.md + SEO_STRATEGY.md
+ HANDOFF docs). **Do marketing there, not code in the repos.**

- **Live & selling:** Silver Falls ($14.99, Bokun 1241601) + Multnomah on Viator,
  **page-one but ZERO reviews** (cold-start is the only blocker). Also iOS
  (id6767043111) + Android. Direct sales via rangertales.com (Bokun/Stripe ≈4.5%
  vs Viator's cut).
- **Delivered this session (nothing sent — all drafts for Mike to fire):**
  - `Ranger Tales Strategy/marketing/silver_falls_launch_kit.html` — review
    flywheel + outreach + link discipline (Viator for reviews → rangertales.com for margin).
  - **Outreach hit-list** (the money-this-week play — high-intent trip planners,
    NOT broad TikTok): Reddit searches (r/oregon, r/askportland, r/hiking, r/PNW —
    `?q=silver falls&sort=new`), travel forums (Fodors/TripAdvisor/Wanderlog), FB
    groups (Oregon Hikers, PNW Hiking, Oregon Waterfalls, Silverton/Salem), Komoot/AllTrails.
  - **Footage:** 6 free (Pexels, no-attribution) waterfall clips downloaded to
    `Ranger Tales Video/footage/pexels-waterfall-*.mp4` (best: 12955734, 8859849,
    5896379, 6394054; 5835778 = Niagara for that tour). Mike pairs one with a fresh
    Boone story via his proven `make_video.sh` pipeline. He's writing the story.
- **Next when he says go:** exact FB groups + PNW creator DM list; more TikTok
  scripts from his real narration; Multnomah kit. Key insight he confirmed: TikTok
  is broad/low-intent for trips; the warm money is trip-planners in outreach.

### Working style (both projects)
Direct, results-oriented, copy-paste-ready, plain terms (not a coder). Voice-to-text
— parse intent (homophones). Exhausted/broke/ferocious — SUBTRACT work, action over
explanation, one recommendation not 12 options. Verify patches before claiming success.
