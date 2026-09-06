# LIVE_LOG_SPEC.md — TikTok LIVE analytics log for the Kalodata dashboard

## Context (read first)

- Existing project: `~/kalodata/dashboard.py`, local web app on port 8787, phone-accessible on the LAN.
- It already has: QVC shop scanner (paginated to 500 products, revenue-band filter), single-product lookup with bulk creator-count loading, launch-date filter, Card $ / Ad % columns. Uses a SQLite cache DB shared with `kalodata_qvc.py`.
- Owner is a TikTok Shop **affiliate creator** (not a seller). Streams from TikTok LIVE Studio on a MacBook Pro. Analytics come from TikTok Shop Creator website → LIVE Manager → LIVE Board (during stream) and Analytics > LIVE Analytics > All LIVE videos (after), plus "Creator Live Performance" CSV exports.
- Goal: turn this dashboard into the TikTok LIVE dashboard. Add a `live_log` feature so that after ~10 streams the "when to end the live" rule is driven by his own numbers, and time-slot analysis becomes possible.
- Style: maximum automation, copy-paste-ready, proceed on reasonable assumptions, don't over-clarify. Reuse the existing Flask/SQLite patterns and page styling in `dashboard.py`.

## Task

Add a LIVE section to the dashboard with three parts: (1) stream log, (2) mid-stream check-ins, (3) trends + decision rule. Keep everything in the existing SQLite DB. Do not break existing scanner routes.

### 1. Schema

```sql
CREATE TABLE IF NOT EXISTS live_stream (
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,             -- YYYY-MM-DD (local)
  start_time TEXT,                -- HH:MM local
  duration_min INTEGER,
  title TEXT,
  products TEXT,                  -- comma list of products featured
  impressions INTEGER,
  join_rate REAL,                 -- viewers / impressions
  unique_viewers INTEGER,
  peak_concurrent INTEGER,
  avg_concurrent INTEGER,
  avg_watch_sec INTEGER,
  fyp_pct REAL,                   -- % of viewers from For You
  following_pct REAL,
  comments INTEGER,
  likes INTEGER,
  shares INTEGER,
  new_followers INTEGER,
  product_clicks INTEGER,
  ctr REAL,                       -- product clicks / product impressions
  cto REAL,                       -- orders / product clicks (TikTok calls it C_O / CTOR)
  orders INTEGER,
  gmv REAL,
  est_commission REAL,
  aov REAL,                       -- gmv / orders (derive if blank)
  gpm REAL,                       -- gmv / views * 1000 (derive if blank)
  pcv_note TEXT,                  -- what was happening at peak concurrent
  debrief TEXT,                   -- 30-min post-stream notes
  improved_metric TEXT,           -- one metric that improved vs last stream
  declined_metric TEXT,           -- one metric that declined
  next_test TEXT,                 -- single-variable test for next stream
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_checkin (
  id INTEGER PRIMARY KEY,
  stream_id INTEGER REFERENCES live_stream(id),
  minute INTEGER NOT NULL,        -- minutes since stream start
  entries INTEGER,                -- new viewers entered since last check
  concurrent INTEGER,
  comments INTEGER,               -- since last check
  product_clicks INTEGER,         -- since last check
  orders INTEGER,                 -- since last check
  gmv REAL,                       -- since last check
  pinned_product TEXT,
  note TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

Derive on read: `gpm = gmv / unique_viewers * 1000`, `aov = gmv / orders`, `comments_per_order = comments / orders`, `orders_per_hour = orders / (duration_min/60)`, `gmv_per_hour`.

### 2. Routes / pages

- `GET /live` — table of all streams, newest first, with derived columns. Sortable. Row click → detail.
- `GET|POST /live/new` — form to add a stream (all fields optional except date). Phone-friendly (big inputs, numeric keyboards). Prefill date/time with now.
- `GET|POST /live/<id>` — detail + edit, plus the check-in timeline and a small chart of concurrent / entries / gmv per check-in.
- `POST /live/<id>/checkin` — quick form: minute (default = minutes since start_time), entries, concurrent, comments, clicks, orders, gmv, pinned product, note. This is used on the iPad during the stream every 15 min, so make it one screen, one tap to submit.
- `GET /live/<id>/decision` (or a panel on the detail page) — see §3.
- `GET /live/trends` — charts across streams: GPM, AWT, CTR, C_O, orders/hr, PCV over time; GMV by start-hour and by weekday (time-slot analysis); GMV by product (split `products` on comma).
- `POST /live/import` — upload a Creator Live Performance CSV export. **The export column names are not known: on first run, print the header, then write a mapping dict at the top of the import code and map what exists; leave the rest NULL.** One row per stream; upsert on (date, start_time).

### 3. Decision rule (in-stream "should I end?")

Compute from the last three check-ins of the current stream and show a status badge on the detail page:

- **STAY** if `entries` is flat or rising across the last 3 check-ins, regardless of concurrent. New traffic = algorithm still investing.
- **SWAP PRODUCT / CHANGE FORMAT** if concurrent is stable but `orders` stalled for 2 check-ins, or check-in CTR (`product_clicks / entries`) < 3%. Also flag if the same pinned product has been up > 18 min.
- **END ON A HIGH** if BOTH `entries` AND check-in GMV have declined for 3 consecutive check-ins AND at least one "swap" flag has already fired earlier in this stream. Show reminder: run best closer, pin comment with top 3 products, then end.
- **DON'T RESTART** note: never end-and-restart before minute 60 unless technically broken (restart resets the algorithm's learning phase).

Also show phase label from minute: 0–15 "Active push", 15–60 "Learning", 60+ "Adapting".

### 4. Benchmarks to display next to metrics (from public sources, 2026)

- AWT: < 90 s structural problem; 90 s–3 min optimization zone; > 3 min algorithmic sweet spot.
- Product CTR: below ~3% → fix pin timing / verbal CTA.
- Comments per order: 15–30 healthy; > 50 hollow engagement; < 10 under-engaged.
- FYP share > 40% = earning organic distribution; Following > 50% = need cold reach.
- Follower conversion 3–5% of non-followers.
- Cart→checkout > 50% strong (only if the export includes it).
- Algorithm phases: minutes 0–15 automatic broad push (first 1–2 min weighted most); 0–60 learning from enter/leave, comments, shares, clicks, sales; 60+ targeted audience, continuously reassessed.
- Revenue-window check: on the trends page, plot orders vs minute across check-ins; if > 80% of GMV lands in one 20–30 min window across most streams, recommend shorter, more frequent streams.

### 5. Post-stream loop (encode as the edit form's bottom section)

Three required-ish text fields after each stream: one metric that improved (double down), one that declined (diagnose), one single-variable test for next time. Show last stream's `next_test` at the top of the new-stream form so it's carried forward.

### 6. Done when

- `python3 dashboard.py` still serves existing scanner pages.
- `/live`, `/live/new`, `/live/<id>`, check-in POST, `/live/trends`, `/live/import` all work on phone width.
- Decision badge updates after each check-in.
- Import handles a real CSV export (ask for a sample file if none is in the folder; otherwise build the mapping stub and print headers).

## Sources used for the rule/benchmarks
- TikTok Shop Academy: "How to read live performances and logic of recommendation traffic" (funnel: duration → join rate → view time → CTR → C_O; GPM = CTR × C_O × AOV × 1000)
- TikTok Shop Academy: "LIVE Manager Analytics" (LIVE Board during stream; Analytics > LIVE Analytics after)
- BEAR MINIMUM, "Why isn't your TikTok LIVE getting traffic?" (Jul 2026) — algorithm phases, don't restart
- MomentIQ, "TikTok Shop Live Commerce Analytics Decoded" and "Build a Real-Time Live Commerce Dashboard" (Mar 2026) — benchmarks, 3% CTR swap rule, 12–18 min attention cycles, revenue-window analysis, residual replay sales
