#!/usr/bin/env python3
"""
QVC Opportunity Dashboard — local web UI for the Kalodata Open API.

Run:    python3 ~/kalodata/dashboard.py
Open:   http://localhost:8787   (or http://<mac-name>.local:8787 from phone)

Uses the same key file (~/.config/kalodata/env) and cache DB
(~/kalodata/cache.db) as kalodata_qvc.py. Stdlib only.
"""
import base64, csv, io, json, os, re, sqlite3, sys, threading, time, zipfile
import datetime as dt
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler

BASE_URL = "https://www.kalodata.com/openapi/v1"
REGION, LANGUAGE, CURRENCY = "US", "en-US", "USD"
DEFAULT_SHOP = {"shop_id": "7495811038271212487", "shop_name": "QVC, Inc"}
PORT = int(os.environ.get("PORT", 8787))  # hosts (Railway) inject $PORT
DETAIL_TTL_DAYS = 7

HOME = os.path.expanduser("~")
ENV_PATH = os.path.join(HOME, ".config", "kalodata", "env")
# DATA_DIR is overridable via env so a hosted volume (e.g. Railway) can persist
# the cache across redeploys; falls back to ~/kalodata locally.
DATA_DIR = os.environ.get("KALO_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "cache.db")

CREDITS = {"used": 0.0}
LOCK = threading.Lock()


def load_key():
    env = os.environ.get("KALODATA_API_KEY")
    if env:
        return env.strip()
    try:
        with open(ENV_PATH) as f:
            for line in f:
                if line.strip().startswith("KALODATA_API_KEY="):
                    return line.strip().split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    # No key: fine for LIVE-log-only use (needs no Kalodata API). The QVC scanner
    # tabs stay disabled until a key is set. Lets the dashboard run on any Mac
    # (e.g. the MacBook) with zero config just for the LIVE Log.
    print("No KALODATA_API_KEY found — QVC scanner disabled; LIVE Log works fine.")
    return None


KEY = load_key()


def load_password():
    """Optional. If DASHBOARD_PASSWORD is set in the env file, the dashboard
    requires it (Basic Auth) before serving anything. If unset, no auth —
    safe for local-only use, but set one before exposing via a tunnel."""
    env = os.environ.get("DASHBOARD_PASSWORD")
    if env is not None:
        return env.strip() or None
    try:
        with open(ENV_PATH) as f:
            for line in f:
                if line.strip().startswith("DASHBOARD_PASSWORD="):
                    return line.strip().split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    return None


DASH_PW = load_password()


def api(path, body, rows_hint=100):
    data = json.dumps(body).encode()
    req = urllib.request.Request(BASE_URL + path, data=data, headers={
        "Content-Type": "application/json", "X-API-Key": KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read().decode())
    if not out.get("success"):
        raise RuntimeError(out.get("message") or "API error")
    with LOCK:
        if path.endswith("/rank"):
            n = len(out.get("data") or []) or 1
            CREDITS["used"] += 0.1 * ((n + 99) // 100)
        else:
            CREDITS["used"] += 0.1
    return out.get("data")


def seed_cache_if_needed():
    """When running with an external data dir (e.g. a Railway volume) that has
    no cache yet, seed it once from the cache.db bundled next to this script.
    Lets us carry the Mac's already-paid product cache up to the cloud, and
    only runs when the volume is empty so later scans persist."""
    if not os.environ.get("KALO_DATA_DIR"):
        return  # local: DATA_DIR already IS where cache.db lives
    # "Empty" = details table has 0 rows (an empty cache.db FILE may already
    # exist from a prior boot, so checking file size isn't enough).
    try:
        con = sqlite3.connect(DB_PATH)
        n = con.execute("SELECT COUNT(*) FROM details").fetchone()[0]
        con.close()
        if n > 0:
            return  # volume already has real data — don't clobber it
    except Exception:
        pass  # no DB/table yet — treat as empty and seed
    seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.db")
    if os.path.exists(seed) and os.path.abspath(seed) != os.path.abspath(DB_PATH):
        import shutil
        os.makedirs(DATA_DIR, exist_ok=True)
        shutil.copyfile(seed, DB_PATH)
        print(f"Seeded cache from {seed} -> {DB_PATH} "
              f"({os.path.getsize(DB_PATH)} bytes)")


def seed_live_if_needed():
    """On a hosted volume with no live-log data yet, copy the live_stream +
    live_checkin rows from the deploy-bundled cache.db (Mike's Mac data) so the
    LIVE Log + Trends work on Railway too. Only runs when the volume's live_stream
    is empty, so later cloud-logged streams are never clobbered."""
    if not os.environ.get("KALO_DATA_DIR"):
        return  # local already IS the source of truth
    seed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache.db")
    if not os.path.exists(seed) or os.path.abspath(seed) == os.path.abspath(DB_PATH):
        return
    con = db()  # ensures live tables exist on the volume
    try:
        if con.execute("SELECT COUNT(*) FROM live_stream").fetchone()[0] > 0:
            return  # volume already has live data — don't touch it
        if not sqlite3.connect(seed).execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='live_stream'").fetchone():
            return  # seed has no live data to copy
        con.execute("ATTACH ? AS seed", (seed,))
        con.execute("INSERT INTO live_stream SELECT * FROM seed.live_stream")
        con.execute("INSERT INTO live_checkin SELECT * FROM seed.live_checkin")
        con.commit()
        con.execute("DETACH seed")
        n = con.execute("SELECT COUNT(*) FROM live_stream").fetchone()[0]
        print(f"Seeded live log from bundled cache.db ({n} streams)")
    except Exception as e:
        print(f"seed_live_if_needed skipped: {e}")
    finally:
        con.close()


def db():
    os.makedirs(DATA_DIR, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS details(
        product_id TEXT PRIMARY KEY, fetched_at TEXT,
        creator_count INTEGER, video_count INTEGER, live_count INTEGER,
        raw TEXT, date_range TEXT)""")
    # migrate DBs created before the date_range column existed
    if "date_range" not in [c[1] for c in
                            con.execute("PRAGMA table_info(details)").fetchall()]:
        con.execute("ALTER TABLE details ADD COLUMN date_range TEXT")
    con.execute("""CREATE TABLE IF NOT EXISTS rank_history(
        run_date TEXT, product_id TEXT, rank INTEGER,
        units INTEGER, revenue REAL, PRIMARY KEY (run_date, product_id))""")
    con.execute("""CREATE TABLE IF NOT EXISTS saved_shops(
        shop_id TEXT PRIMARY KEY, shop_name TEXT, added_at TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS live_stream(
        id INTEGER PRIMARY KEY, room_id TEXT, date TEXT NOT NULL, start_time TEXT,
        duration_min INTEGER, title TEXT, products TEXT,
        impressions INTEGER, join_rate REAL, unique_viewers INTEGER,
        peak_concurrent INTEGER, avg_concurrent INTEGER, avg_watch_sec INTEGER,
        fyp_pct REAL, following_pct REAL, comments INTEGER, likes INTEGER,
        shares INTEGER, new_followers INTEGER, product_clicks INTEGER,
        ctr REAL, cto REAL, orders INTEGER, gmv REAL, est_commission REAL,
        aov REAL, gpm REAL, pcv_note TEXT, debrief TEXT,
        improved_metric TEXT, declined_metric TEXT, next_test TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    con.execute("""CREATE TABLE IF NOT EXISTS live_checkin(
        id INTEGER PRIMARY KEY,
        stream_id INTEGER REFERENCES live_stream(id),
        minute INTEGER NOT NULL, entries INTEGER, concurrent INTEGER,
        comments INTEGER, product_clicks INTEGER, orders INTEGER, gmv REAL,
        pinned_product TEXT, note TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    # migrate live_stream rows created before room_id existed
    if "room_id" not in [c[1] for c in
                         con.execute("PRAGMA table_info(live_stream)").fetchall()]:
        con.execute("ALTER TABLE live_stream ADD COLUMN room_id TEXT")
    return con


def detail_from_cache(con, pid, date_range, force=False):
    cutoff = (dt.datetime.now() - dt.timedelta(days=DETAIL_TTL_DAYS)).isoformat()
    cur = con.execute("SELECT fetched_at, creator_count, video_count, "
                      "live_count, raw, date_range FROM details WHERE product_id=?",
                      (pid,)).fetchone()
    # HIT only if same time window (date_range) AND within TTL — otherwise the
    # cached numbers are for the wrong period (the 7-day-vs-30-day bug).
    if cur and cur[0] >= cutoff and not force and cur[5] == date_range:
        return {"creator_number": cur[1], "video_number": cur[2],
                "live_number": cur[3], **json.loads(cur[4] or "{}")}
    return None


def detail_fetch(pid, date_range):
    """API call only — no DB. Safe to run in a worker thread."""
    return api("/product/detail", {
        "region": REGION, "language": LANGUAGE, "currency": CURRENCY,
        "date_range": date_range, "product_id": pid}) or {}


def detail_store(con, pid, d, date_range):
    con.execute("INSERT OR REPLACE INTO details(product_id, fetched_at, "
                "creator_count, video_count, live_count, raw, date_range) "
                "VALUES (?,?,?,?,?,?,?)",
                (pid, dt.datetime.now().isoformat(), d.get("creator_number"),
                 d.get("video_number"), d.get("live_number"), json.dumps(d),
                 date_range))


def get_detail(con, pid, date_range, force=False):
    d = detail_from_cache(con, pid, date_range, force)
    if d is not None:
        return d
    d = detail_fetch(pid, date_range)
    detail_store(con, pid, d, date_range)
    con.commit()
    time.sleep(0.3)
    return d


def scan(shop_id, window, top, min_units, refresh, pages=1,
         rev_min=None, rev_max=None, keyword=None, launched=None,
         sort="per_creator", confirmed=False):
    date_range = {1: "lastDay", 7: "last7Day", 30: "last30Day"}[window]
    con = db()
    today = dt.date.today().isoformat()
    products = []
    for pg in range(1, max(1, min(int(pages), 5)) + 1):
        body = {"region": REGION, "language": LANGUAGE,
                "currency": CURRENCY, "date_range": date_range,
                "page": pg, "page_size": 100}
        if keyword:
            body["keyword"] = keyword
        elif shop_id and shop_id != "ALL":
            body["shop_id"] = shop_id
        # else: no shop_id + no keyword = global rank across ALL shops
        if launched:
            body["launch_date"] = launched
        batch = api("/product/rank", body) or []
        products.extend(batch)
        if len(batch) < 100:
            break
    rows = []
    for i, p in enumerate(products, 1):
        pid = str(p["product_id"])
        con.execute("INSERT OR REPLACE INTO rank_history VALUES (?,?,?,?,?)",
                    (today, pid, i, int(p.get("sales_volumn") or 0),
                     float(p.get("revenue") or 0)))
        rev = float(p.get("revenue") or 0)
        vid_r = float(p.get("video_revenue") or 0)
        live_r = float(p.get("live_revenue") or 0)
        show_r = float(p.get("showcase_revenue") or 0)
        card_r = max(0.0, rev - vid_r - live_r - show_r)
        rows.append({"rank": i, "product_id": pid,
                     "name": p.get("product_name"),
                     "units": int(p.get("sales_volumn") or 0),
                     "revenue": rev,
                     "card_rev": round(card_r),
                     "ad_pct": round(card_r / rev * 100) if rev else None,
                     "price": p.get("unit_price"),
                     "commission_pct": p.get("commission_rate"),
                     "growth_pct": p.get("revenue_growth_rate"),
                     "launch_date": p.get("launch_date")})
    con.commit()
    kept = [r for r in rows if r["units"] >= min_units
            and (rev_min is None or r["revenue"] >= rev_min)
            and (rev_max is None or r["revenue"] <= rev_max)]
    targets = kept[:top]
    detail_map = {}
    misses = []
    for r in targets:
        d = detail_from_cache(con, r["product_id"], date_range, force=refresh)
        if d is not None:
            detail_map[r["product_id"]] = d
        else:
            misses.append(r["product_id"])
    # Cost guard: only cache-MISSES cost money (~1c each). If the real spend
    # crosses 25c, stop and hand the client an estimate to confirm — anything
    # already cached is free and excluded, so the number is exact, not worst-case.
    new_cost = round(0.01 * len(misses), 2)
    if not confirmed and new_cost > 0.25:
        con.close()
        return {"needs_confirm": True, "estimate": new_cost,
                "n_new": len(misses), "n_cached": len(targets) - len(misses)}
    # Fetch cache-misses concurrently (8 at a time) so a 500-product deep
    # scan finishes in ~40-60s instead of ~6min — under Cloudflare's ~100s
    # tunnel timeout. API calls are thread-safe; DB writes stay in main thread.
    if misses:
        def _worker(pid):
            try:
                return pid, detail_fetch(pid, date_range)
            except Exception:
                return pid, {}
        with ThreadPoolExecutor(max_workers=8) as ex:
            for pid, d in ex.map(_worker, misses):
                detail_map[pid] = d
                detail_store(con, pid, d, date_range)
        con.commit()
    for r in targets:
        d = detail_map.get(r["product_id"], {})
        creators = d.get("creator_number")
        r["creators"] = creators
        r["videos"] = d.get("video_number")
        r["lives"] = d.get("live_number")
        rate = (r["commission_pct"] or 0) / 100.0
        pool = round(r["revenue"] * rate)
        r["pool"] = pool
        r["per_creator"] = round(pool / creators) if creators else None
        r["units_per_creator"] = round(r["units"] / creators, 1) if creators else None
    BIG = float("inf")
    if sort == "videos":
        # fewest videos first (0 = nobody's made a video yet); undetailed last
        kept.sort(key=lambda r: r["videos"] if r.get("videos") is not None else BIG)
    elif sort == "creators":
        # fewest creators first; undetailed last
        kept.sort(key=lambda r: r["creators"] if r.get("creators") is not None else BIG)
    else:
        kept.sort(key=lambda r: (r.get("per_creator") is None,
                                 -(r.get("per_creator") or 0)))
    con.close()
    return kept


def product_search(keyword, window, shop_id=None):
    date_range = {1: "lastDay", 7: "last7Day", 30: "last30Day"}[window]
    body = {"region": REGION, "language": LANGUAGE, "currency": CURRENCY,
            "date_range": date_range, "keyword": keyword,
            "page": 1, "page_size": 10}
    if shop_id:
        body["shop_id"] = shop_id
    return api("/product/rank", body) or []


def product_detail(pid, window):
    date_range = {1: "lastDay", 7: "last7Day", 30: "last30Day"}[window]
    con = db()
    d = get_detail(con, pid, date_range, force=False)
    con.close()
    return d


def shop_search(keyword):
    return api("/shop/rank", {
        "region": REGION, "language": LANGUAGE, "currency": CURRENCY,
        "date_range": "last7Day", "keyword": keyword,
        "page": 1, "page_size": 8}) or []


def save_shop(shop_id, shop_name):
    con = db()
    con.execute("INSERT OR REPLACE INTO saved_shops VALUES (?,?,?)",
                (str(shop_id), shop_name or str(shop_id),
                 dt.datetime.now().isoformat()))
    con.commit()
    con.close()
    return {"ok": True}


def saved_shops():
    con = db()
    rows = con.execute("SELECT shop_id, shop_name FROM saved_shops "
                       "ORDER BY shop_name COLLATE NOCASE").fetchall()
    con.close()
    return [{"shop_id": r[0], "shop_name": r[1]} for r in rows]


def remove_shop(shop_id):
    con = db()
    con.execute("DELETE FROM saved_shops WHERE shop_id=?", (str(shop_id),))
    con.commit()
    con.close()
    return {"ok": True}


def livestreams(shop_id, window, pages=3):
    """Top livestreams selling the shop's products, ranked by revenue. Their
    pagination repeats the same page, so we dedupe by livestream_id and stop
    once a page adds nothing new."""
    date_range = {1: "lastDay", 7: "last7Day", 30: "last30Day"}[window]
    seen = set()
    rows = []
    for pg in range(1, max(1, min(int(pages), 3)) + 1):
        body = {"region": REGION, "language": LANGUAGE, "currency": CURRENCY,
                "date_range": date_range, "page": pg, "page_size": 100}
        if shop_id and shop_id != "ALL":
            body["shop_id"] = shop_id
        batch = api("/livestream/rank", body) or []
        new = 0
        for r in batch:
            lid = str(r.get("livestream_id"))
            if lid in seen:
                continue
            seen.add(lid)
            new += 1
            rows.append({
                "livestream_id": lid,
                "creator_handle": r.get("creator_handle"),
                "title": r.get("livestream_title"),
                "revenue": float(r.get("revenue") or 0),
                "views": int(r.get("views") or 0),
                "unit_price": float(r.get("unit_price") or 0),
                "duration_min": round(int(r.get("livestream_duration") or 0) / 60)})
        if new == 0 or len(batch) < 100:
            break
    rows.sort(key=lambda r: -r["revenue"])
    return rows


def cached_products(limit=2000):
    """Rebuild product rows from the local cache only — NO API calls, so it
    works even at $0 credit balance. Pulls everything we've already paid to
    detail. Same row shape as scan() so the table + CSV export just work."""
    con = db()
    rows = []
    cur = con.execute("SELECT product_id, fetched_at, creator_count, "
                      "video_count, live_count, raw FROM details "
                      "ORDER BY fetched_at DESC LIMIT ?", (limit,))
    for pid, fetched_at, cc, vc, lc, raw in cur.fetchall():
        d = json.loads(raw or "{}")
        rev = float(d.get("revenue") or 0)
        card_r = max(0.0, rev - float(d.get("video_revenue") or 0)
                     - float(d.get("live_revenue") or 0)
                     - float(d.get("showcase_revenue") or 0))
        units = int(d.get("sales_volumn") or 0)
        comm = d.get("commission_rate")
        pool = round(rev * (comm or 0) / 100.0)
        rows.append({
            "product_id": pid, "name": d.get("product_name"),
            "units": units, "revenue": rev,
            "creators": cc, "videos": vc, "lives": lc,
            "per_creator": round(pool / cc) if cc else None,
            "pool": pool,
            "units_per_creator": round(units / cc, 1) if cc else None,
            "card_rev": round(card_r),
            "ad_pct": round(card_r / rev * 100) if rev else None,
            "price": d.get("unit_price") or d.get("min_price"),
            "commission_pct": comm,
            "growth_pct": d.get("revenue_growth_rate"),
            "launch_date": d.get("launch_date"),
        })
    con.close()
    return rows


# ---------------------------------------------------------------------------
# TikTok LIVE performance log (LIVE_LOG_SPEC.md). Mike's OWN stream data —
# NO Kalodata credits involved. All numbers come from the LIVE Board / the
# "Creator Live Performance" CSV export.
# ---------------------------------------------------------------------------

LIVE_STREAM_FIELDS = [
    "room_id",
    "date", "start_time", "duration_min", "title", "products", "impressions",
    "join_rate", "unique_viewers", "peak_concurrent", "avg_concurrent",
    "avg_watch_sec", "fyp_pct", "following_pct", "comments", "likes", "shares",
    "new_followers", "product_clicks", "ctr", "cto", "orders", "gmv",
    "est_commission", "aov", "gpm", "pcv_note", "debrief", "improved_metric",
    "declined_metric", "next_test"]
_INT_FIELDS = {"duration_min", "impressions", "unique_viewers", "peak_concurrent",
               "avg_concurrent", "avg_watch_sec", "comments", "likes", "shares",
               "new_followers", "product_clicks", "orders"}
_FLOAT_FIELDS = {"join_rate", "fyp_pct", "following_pct", "ctr", "cto", "gmv",
                 "est_commission", "aov", "gpm"}


def _num(v, is_int):
    if v in (None, ""):
        return None
    try:
        return int(round(float(v))) if is_int else float(v)
    except (TypeError, ValueError):
        return None


def _coerce_stream(fields):
    """Keep only known columns, coerce numeric strings to numbers."""
    out = {}
    for k in LIVE_STREAM_FIELDS:
        if k not in fields:
            continue
        v = fields[k]
        if k in _INT_FIELDS:
            out[k] = _num(v, True)
        elif k in _FLOAT_FIELDS:
            out[k] = _num(v, False)
        else:
            out[k] = (str(v).strip() or None) if v is not None else None
    return out


def _derive_stream(s):
    """Add computed metrics that may be blank in the raw row (gpm, aov, etc.)."""
    gmv, orders = s.get("gmv"), s.get("orders")
    views = s.get("unique_viewers") or s.get("impressions")
    if s.get("aov") in (None, "") and gmv and orders:
        s["aov"] = round(gmv / orders, 2)
    if s.get("gpm") in (None, "") and gmv and views:
        s["gpm"] = round(gmv / views * 1000, 2)
    if gmv and orders:
        s["comments_per_order"] = round((s.get("comments") or 0) / orders, 1)
    else:
        s["comments_per_order"] = None
    dur = s.get("duration_min")
    if dur:
        hrs = dur / 60.0
        s["orders_per_hour"] = round((orders or 0) / hrs, 1)
        s["gmv_per_hour"] = round((gmv or 0) / hrs)
    else:
        s["orders_per_hour"] = s["gmv_per_hour"] = None
    if s.get("date"):
        try:
            s["weekday"] = dt.date.fromisoformat(s["date"]).strftime("%a")
        except ValueError:
            s["weekday"] = None
    else:
        s["weekday"] = None
    s["start_hour"] = None
    if s.get("start_time") and ":" in str(s["start_time"]):
        try:
            s["start_hour"] = int(str(s["start_time"]).split(":")[0])
        except ValueError:
            pass
    return s


def _row_to_dict(cur, row):
    return {d[0]: row[i] for i, d in enumerate(cur.description)}


def live_save(fields):
    con = db()
    data = _coerce_stream(fields)
    if not data.get("date"):
        data["date"] = dt.date.today().isoformat()
    sid = fields.get("id")
    if sid:
        sid = int(sid)
        cols = [k for k in data if k != "id"]
        if cols:
            con.execute("UPDATE live_stream SET " +
                        ", ".join(f"{c}=?" for c in cols) + " WHERE id=?",
                        [data[c] for c in cols] + [sid])
    else:
        cols = list(data.keys())
        cur = con.execute("INSERT INTO live_stream (" + ", ".join(cols) +
                          ") VALUES (" + ", ".join("?" for _ in cols) + ")",
                          [data[c] for c in cols])
        sid = cur.lastrowid
    con.commit()
    con.close()
    return {"id": sid}


def live_list():
    con = db()
    cur = con.execute("SELECT * FROM live_stream ORDER BY date DESC, "
                      "start_time DESC, id DESC")
    rows = [_derive_stream(_row_to_dict(cur, r)) for r in cur.fetchall()]
    con.close()
    return rows


def live_checkin_add(fields):
    con = db()
    sid = int(fields["stream_id"])
    cols = ["stream_id", "minute", "entries", "concurrent", "comments",
            "product_clicks", "orders", "gmv", "pinned_product", "note"]
    ints = {"minute", "entries", "concurrent", "comments", "product_clicks",
            "orders"}
    vals = {"stream_id": sid, "minute": _num(fields.get("minute"), True) or 0}
    for c in cols[2:]:
        v = fields.get(c)
        if c in ints:
            vals[c] = _num(v, True)
        elif c == "gmv":
            vals[c] = _num(v, False)
        else:
            vals[c] = (str(v).strip() or None) if v is not None else None
    con.execute("INSERT INTO live_checkin (" + ", ".join(cols) + ") VALUES (" +
                ", ".join("?" for _ in cols) + ")", [vals[c] for c in cols])
    con.commit()
    con.close()
    return {"ok": True}


def _checkins(con, sid):
    cur = con.execute("SELECT * FROM live_checkin WHERE stream_id=? "
                      "ORDER BY minute ASC, id ASC", (sid,))
    return [_row_to_dict(cur, r) for r in cur.fetchall()]


def _phase(minute):
    if minute is None:
        return "Active push"
    if minute <= 15:
        return "Active push"
    if minute <= 60:
        return "Learning"
    return "Adapting"


def _swap_flag(window):
    """Given up to the last 3 check-ins, is a SWAP/CHANGE-FORMAT condition met?
    Concurrent stable but orders stalled 2 checks, OR check-in CTR < 3%, OR
    same pinned product held > 18 min. Returns (bool, list-of-reasons)."""
    reasons = []
    if not window:
        return False, reasons
    last = window[-1]
    # CTR = clicks / entries for the latest check-in
    entries = last.get("entries") or 0
    clicks = last.get("product_clicks") or 0
    if entries and clicks / entries < 0.03:
        reasons.append("check-in CTR < 3%")
    # orders stalled for the last 2 check-ins (per-interval orders == 0)
    if len(window) >= 2:
        o2 = [c.get("orders") or 0 for c in window[-2:]]
        cc = [c.get("concurrent") or 0 for c in window[-2:]]
        concurrent_stable = max(cc) == 0 or (min(cc) >= 0.6 * max(cc))
        if concurrent_stable and sum(o2) == 0:
            reasons.append("orders stalled 2 checks while concurrent held")
    # same pinned product spanning > 18 min
    pin = last.get("pinned_product")
    if pin:
        run_start = last.get("minute")
        for c in reversed(window[:-1]):
            if c.get("pinned_product") == pin:
                run_start = c.get("minute")
            else:
                break
        if run_start is not None and last.get("minute") is not None \
                and last["minute"] - run_start > 18:
            reasons.append("same pin up > 18 min")
    return (len(reasons) > 0), reasons


def _declining(vals):
    """True if the last 3 values are strictly decreasing (trend down)."""
    v = [x for x in vals if x is not None]
    return len(v) >= 3 and v[-3] > v[-2] > v[-1]


def _not_declining(vals):
    """Flat or rising across the last 3 (latest >= earliest, not strictly down)."""
    v = [x for x in vals if x is not None]
    if len(v) < 2:
        return True
    if len(v) >= 3 and v[-3] > v[-2] > v[-1]:
        return False
    return v[-1] >= v[-3] if len(v) >= 3 else v[-1] >= v[-2]


def live_decision(checkins):
    """Compute the in-stream badge from the check-in timeline (spec §3)."""
    if not checkins:
        return {"status": "STAY", "phase": "Active push", "minute": None,
                "reasons": ["No check-ins yet — log one every 15 min."],
                "swap_ever": False}
    minute = checkins[-1].get("minute")
    phase = _phase(minute)
    if len(checkins) < 3:
        return {"status": "STAY", "phase": phase, "minute": minute,
                "reasons": ["Need 3 check-ins before the rule kicks in; "
                            "keep going and log every 15 min."],
                "swap_ever": False}
    last3 = checkins[-3:]
    entries = [c.get("entries") for c in last3]
    gmv = [c.get("gmv") for c in last3]
    # Did a swap flag fire at any earlier point in the stream?
    swap_ever = False
    for i in range(1, len(checkins)):
        fired, _ = _swap_flag(checkins[max(0, i - 2):i + 1])
        if fired and i < len(checkins) - 1:
            swap_ever = True
            break
    swap_now, swap_reasons = _swap_flag(last3)
    reasons = []
    # Zero-conversion abort: past the active-push window (>=45 min) with 0 orders
    # for the whole stream after a swap already fired = the room won't convert
    # today. Sitting longer is dead air and teaches the algorithm your lives
    # don't sell (shrinks your next opening push). End clean.
    total_orders = sum((c.get("orders") or 0) for c in checkins)
    if total_orders == 0 and (minute or 0) >= 45 and (swap_ever or swap_now):
        return {"status": "END — NOT CONVERTING", "phase": phase,
                "minute": minute, "swap_ever": True,
                "reasons": ["Past the learning window with 0 orders after a swap — "
                            "this room isn't buying today.",
                            "End clean now: best closer, pin a comment with your top "
                            "3 products, then end. Protect your next stream's push; "
                            "come back on schedule tomorrow."]}
    if _declining(entries) and _declining(gmv) and (swap_ever or swap_now):
        return {"status": "END ON A HIGH", "phase": phase, "minute": minute,
                "swap_ever": swap_ever or swap_now,
                "reasons": ["Entries AND GMV down 3 checks, swap already tried.",
                            "Run your best closer, pin a comment with the top 3 "
                            "products, then end with cards live "
                            "(residual sales = 15-30%)."]}
    if swap_now:
        return {"status": "SWAP / CHANGE FORMAT", "phase": phase,
                "minute": minute, "swap_ever": True, "reasons": swap_reasons +
                ["Swap product, run an engagement bomb, or change segment type."]}
    if _not_declining(entries):
        reasons.append("Entries flat or rising over the last 3 checks — the "
                       "algorithm is still investing. Keep going.")
    else:
        reasons.append("Entries softening but no swap flag yet — hold, prep a "
                       "format change.")
    if minute is not None and minute < 60:
        reasons.append("Never end-and-restart before minute 60 (resets the "
                       "algorithm's learning).")
    return {"status": "STAY", "phase": phase, "minute": minute,
            "swap_ever": swap_ever, "reasons": reasons}


def live_get(sid):
    con = db()
    sid = int(sid)
    cur = con.execute("SELECT * FROM live_stream WHERE id=?", (sid,))
    row = cur.fetchone()
    if not row:
        con.close()
        return {"error": "not found"}
    stream = _derive_stream(_row_to_dict(cur, row))
    checkins = _checkins(con, sid)
    con.close()
    return {"stream": stream, "checkins": checkins,
            "decision": live_decision(checkins)}


def live_delete(sid):
    con = db()
    sid = int(sid)
    con.execute("DELETE FROM live_checkin WHERE stream_id=?", (sid,))
    con.execute("DELETE FROM live_stream WHERE id=?", (sid,))
    con.commit()
    con.close()
    return {"ok": True}


def live_find_by_room(room_id):
    """Return the live_stream id for a TikTok Room ID, or None. Used by the
    importers to merge the interval export + the summary export for one stream."""
    if not room_id:
        return None
    con = db()
    r = con.execute("SELECT id FROM live_stream WHERE room_id=?",
                    (str(room_id),)).fetchone()
    con.close()
    return r[0] if r else None


def live_clear_checkins(sid):
    con = db()
    con.execute("DELETE FROM live_checkin WHERE stream_id=?", (int(sid),))
    con.commit()
    con.close()


def live_trends():
    """Cross-stream aggregates for the charts: per-stream metric series over
    time, GMV by start-hour and weekday, GMV by product."""
    streams = live_list()
    series = list(reversed(streams))  # oldest first for trend lines
    by_hour, by_day, by_product = {}, {}, {}
    day_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for s in streams:
        g = s.get("gmv") or 0
        if s.get("start_hour") is not None:
            by_hour[s["start_hour"]] = by_hour.get(s["start_hour"], 0) + g
        if s.get("weekday"):
            by_day[s["weekday"]] = by_day.get(s["weekday"], 0) + g
        for p in (s.get("products") or "").split(","):
            p = p.strip()
            if p:
                by_product[p] = by_product.get(p, 0) + g
    return {
        "series": [{"label": (s.get("date") or "") +
                    (" " + s["start_time"] if s.get("start_time") else ""),
                    "gpm": s.get("gpm"), "avg_watch_sec": s.get("avg_watch_sec"),
                    "ctr": s.get("ctr"), "cto": s.get("cto"),
                    "orders_per_hour": s.get("orders_per_hour"),
                    "peak_concurrent": s.get("peak_concurrent"),
                    "gmv": s.get("gmv")} for s in series],
        "by_hour": [{"k": h, "v": round(by_hour[h])}
                    for h in sorted(by_hour)],
        "by_weekday": [{"k": d, "v": round(by_day[d])}
                       for d in day_order if d in by_day],
        "by_product": sorted(
            [{"k": k, "v": round(v)} for k, v in by_product.items()],
            key=lambda x: -x["v"])[:20],
        "n_streams": len(streams),
    }


# Creator Live Performance CSV import. The real export column names are not
# documented, so we map a broad set of aliases (normalized: lowercased,
# non-alphanumeric stripped) onto our fields. On import we PRINT the header so
# unmapped columns can be added here later; unmapped fields stay NULL.
_CSV_ALIASES = {
    "date": ["date", "livedate", "day", "streamdate"],
    "start_time": ["starttime", "time", "livestarttime", "startedat"],
    "duration_min": ["duration", "durationmin", "durationminutes", "liveduration",
                     "length", "lengthmin"],
    "title": ["title", "livetitle", "name"],
    "products": ["products", "product", "productsfeatured", "items"],
    "impressions": ["impressions", "impression", "reach", "totalimpressions"],
    "unique_viewers": ["uniqueviewers", "viewers", "views", "totalviewers",
                       "uv", "audience"],
    "peak_concurrent": ["peakconcurrent", "peakviewers", "pcv",
                        "maxconcurrent", "peakccu"],
    "avg_concurrent": ["avgconcurrent", "averageconcurrent", "avgccu",
                       "averageviewers"],
    "avg_watch_sec": ["avgwatchtime", "averagewatchtime", "avgwatchsec",
                      "watchtime", "avgviewduration", "averagewatchtimes"],
    "join_rate": ["joinrate", "openrate"],
    "fyp_pct": ["fyp", "foryou", "foryoupct", "fyppct", "recommendpct"],
    "following_pct": ["following", "followingpct", "follower", "followerspct"],
    "comments": ["comments", "commentcount", "totalcomments"],
    "likes": ["likes", "likecount", "totallikes"],
    "shares": ["shares", "sharecount", "totalshares"],
    "new_followers": ["newfollowers", "followersgained", "netfollowers",
                     "followers"],
    "product_clicks": ["productclicks", "clicks", "productimpressionclicks",
                       "totalproductclicks"],
    "ctr": ["ctr", "productctr", "clickthroughrate"],
    "cto": ["cto", "ctor", "clicktoorder", "conversionrate", "co"],
    "orders": ["orders", "ordercount", "paidorders", "createdorders",
               "totalorders"],
    "gmv": ["gmv", "revenue", "totalgmv", "grossmerchandisevalue", "sales"],
    "est_commission": ["commission", "estcommission", "estimatedcommission",
                       "earnings", "affiliatecommission"],
    "aov": ["aov", "averageordervalue"],
    "gpm": ["gpm", "grossperminute", "gmvper1000"],
}


def _norm_header(h):
    return "".join(ch for ch in h.lower() if ch.isalnum())


def live_import(csv_text):
    import csv as _csv
    import io as _io
    reader = _csv.reader(_io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return {"error": "empty CSV"}
    header = rows[0]
    print("[live_import] CSV header:", header)  # so unmapped cols are visible
    norm = [_norm_header(h) for h in header]
    # build column-index -> our-field map
    col_field = {}
    for field, aliases in _CSV_ALIASES.items():
        alias_set = {_norm_header(a) for a in aliases}
        for i, nh in enumerate(norm):
            if nh in alias_set and field not in col_field.values():
                col_field[i] = field
                break
    if not col_field:
        return {"error": "no recognizable columns", "header": header,
                "hint": "add these names to _CSV_ALIASES in dashboard.py"}
    con = db()
    imported = 0
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        fields = {}
        for i, field in col_field.items():
            if i < len(r):
                fields[field] = r[i]
        data = _coerce_stream(fields)
        if not data.get("date"):
            continue
        # upsert on (date, start_time)
        existing = con.execute(
            "SELECT id FROM live_stream WHERE date=? AND "
            "IFNULL(start_time,'')=IFNULL(?,'')",
            (data["date"], data.get("start_time"))).fetchone()
        cols = list(data.keys())
        if existing:
            upd = [c for c in cols if c != "date"]
            if upd:
                con.execute("UPDATE live_stream SET " +
                            ", ".join(f"{c}=?" for c in upd) + " WHERE id=?",
                            [data[c] for c in upd] + [existing[0]])
        else:
            con.execute("INSERT INTO live_stream (" + ", ".join(cols) +
                        ") VALUES (" + ", ".join("?" for _ in cols) + ")",
                        [data[c] for c in cols])
        imported += 1
    con.commit()
    con.close()
    mapped = {header[i]: f for i, f in col_field.items()}
    return {"ok": True, "imported": imported, "mapped": mapped,
            "unmapped": [header[i] for i in range(len(header))
                         if i not in col_field]}


# ---------------------------------------------------------------------------
# One-click import of TikTok exports (self-contained, stdlib xlsx parser).
# Powers the dashboard's "Update from latest download" + file-upload buttons.
# Handles BOTH the single-stream LIVE Board export (5-min intervals) and the
# multi-stream "Creator Live Performance" summary. (The CLI scripts
# import_live_board.py / import_creator_performance.py share the same logic.)
# ---------------------------------------------------------------------------
_XN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_XR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_XP = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _xcol(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref or "A").group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xlsx_sheets(raw):
    z = zipfile.ZipFile(io.BytesIO(raw))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(_XN + "si"):
            shared.append("".join(t.text or "" for t in si.iter(_XN + "t")))
    rels = {}
    for rel in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(_XP + "Relationship"):
        rels[rel.get("Id")] = rel.get("Target")
    names = z.namelist()
    sheets = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(_XN + "sheet"):
        target = (rels.get(sh.get(_XR + "id"), "") or "").lstrip("/")
        if target not in names and ("xl/" + target) in names:
            target = "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(target)).iter(_XN + "row"):
            cells, maxc = {}, -1
            for c in row.iter(_XN + "c"):
                idx = _xcol(c.get("r", "A1"))
                v = c.find(_XN + "v")
                val = v.text if v is not None else None
                if c.get("t") == "s" and val is not None:
                    val = shared[int(val)]
                cells[idx] = val
                maxc = max(maxc, idx)
            rows.append([cells.get(i) for i in range(maxc + 1)])
        sheets[sh.get("name")] = rows
    return sheets


def _bnum(v):
    if v is None:
        return 0.0
    s = re.sub(r"[^0-9.\-]", "", str(v))
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def _theme(title):
    tl = (title or "").lower()
    for k in ["convert a bench", "nugget ice", "back to school", "jabberin jack",
              "jabberin' jack", "skil", "power hour", "luxury pillow", "caraway",
              "megachef", "halloween", "meshy mat", "jackery", "vitamix",
              "cuisinart", "blackstone", "bella", "beast"]:
        if k in tl:
            return k.title().replace("Skil", "SKIL")
    words = re.sub(r"[^A-Za-z0-9 ]", "", title or "").split()
    return " ".join(words[:3]) if words else "Untitled"


def _import_single(sheets):
    """Single-stream LIVE Board export -> one stream + 15-min check-ins."""
    allrows = sheets.get("All") or next(iter(sheets.values()))

    def meta(label):
        for r in allrows:
            if r and r[0] == label and len(r) > 1:
                return r[1]
        return None

    m = re.search(r"(\d{1,2}:\d{2})(?::\d{2})?\s+(\d{4}-\d{2}-\d{2})",
                  meta("Started") or "")
    start_time, date = (m.group(1), m.group(2)) if m else (None, None)
    room_id = meta("Room ID")
    room_id = str(room_id) if room_id else None
    dm = re.match(r"(?:(\d+)h)?(?:(\d+)m)?", meta("Duration") or "")
    duration_min = int(dm.group(1) or 0) * 60 + int(dm.group(2) or 0) if dm else None
    hi = next((i for i, r in enumerate(allrows)
               if r and any(str(c).strip() == "Datetime" for c in r if c is not None)), None)
    if hi is None:
        return {"error": "Not a recognizable LIVE Board export (no Datetime header)."}
    hdr = [str(c).strip() if c is not None else "" for c in allrows[hi]]
    data = [r for r in allrows[hi + 1:] if r and r[0]]

    def cell(r, n):
        i = hdr.index(n) if n in hdr else None
        return r[i] if (i is not None and i < len(r)) else None

    def total(n):
        return sum(_bnum(cell(r, n)) for r in data)

    if not date and data:
        date = str(data[0][0])[:10]
    prod_imp, clicks = total("Product Impressions"), total("Product Clicks")
    orders, gmv = int(total("Attributed orders")), total("Attributed GMV")
    concur = [_bnum(cell(r, "Viewers")) for r in data]
    peak = int(max(concur)) if concur else None
    peak_min = (concur.index(max(concur)) + 1) * 5 if concur else 0
    products = ""
    ps = sheets.get("Product")
    if ps and len(ps) > 1:
        pr = sorted([r for r in ps[1:] if r and len(r) > 4 and r[1]],
                    key=lambda r: -_bnum(r[4]))
        products = ", ".join(_theme(str(r[1])) for r in pr[:3])
    stream = {"room_id": room_id, "date": date, "start_time": start_time,
              "duration_min": duration_min, "title": "LIVE " + (date or ""),
              "products": products, "impressions": int(total("LIVE impression")),
              "unique_viewers": int(total("Views")), "peak_concurrent": peak,
              "avg_concurrent": int(round(sum(concur) / len(concur))) if concur else None,
              "comments": int(total("Comments")), "likes": int(total("Likes")),
              "shares": int(total("Shares")), "new_followers": int(total("New followers")),
              "product_clicks": int(clicks),
              "ctr": round(clicks / prod_imp, 6) if prod_imp else None,
              "cto": round(orders / clicks, 6) if clicks else 0.0,
              "orders": orders, "gmv": round(gmv, 2),
              "pcv_note": f"Peak {peak} concurrent at ~min {peak_min}."}
    existing = live_find_by_room(room_id)
    if not existing:
        con = db()
        row = con.execute("SELECT id FROM live_stream WHERE date=? AND "
                          "IFNULL(start_time,'')=IFNULL(?,'')",
                          (date, start_time)).fetchone()
        con.close()
        existing = row[0] if row else None
    if existing:
        sid = existing
        live_clear_checkins(sid)
        live_save({"id": sid, "room_id": room_id, "peak_concurrent": peak,
                   "avg_concurrent": stream["avg_concurrent"],
                   "pcv_note": stream["pcv_note"]})
    else:
        sid = live_save(stream)["id"]
    n = 0
    for b in range(0, len(data), 3):
        chunk = data[b:b + 3]
        if not chunk:
            continue
        last = chunk[-1]
        live_checkin_add({
            "stream_id": sid, "minute": (b // 3 + 1) * 15,
            "entries": int(sum(_bnum(cell(r, "Viewers entering")) for r in chunk)),
            "concurrent": int(_bnum(cell(last, "Viewers"))),
            "comments": int(sum(_bnum(cell(r, "Comments")) for r in chunk)),
            "product_clicks": int(sum(_bnum(cell(r, "Product Clicks")) for r in chunk)),
            "orders": int(sum(_bnum(cell(r, "Attributed orders")) for r in chunk)),
            "gmv": round(sum(_bnum(cell(r, "Attributed GMV")) for r in chunk), 2)})
        n += 1
    g = live_get(sid)
    return {"kind": "single", "id": sid, "merged": bool(existing), "checkins": n,
            "decision": g["decision"], "gmv": round(gmv, 2), "orders": orders,
            "title": stream["title"], "date": date, "start_time": start_time}


_PERF_MAP = {
    "Room Title": ("title", lambda v: str(v).strip() if v else None),
    "Attributed GMV": ("gmv", _bnum), "Attributed orders": ("orders", _bnum),
    "AOV": ("aov", _bnum), "Views": ("unique_viewers", _bnum),
    "Impressions": ("impressions", _bnum), "Watch GPM": ("gpm", _bnum),
    "Avg. viewing duration": ("avg_watch_sec", _bnum),
    "Product clicks": ("product_clicks", _bnum),
    "CTR": ("ctr", lambda v: round(_bnum(v) / 100, 6)),
    "CTOR": ("cto", lambda v: round(_bnum(v) / 100, 6)),
    "New followers": ("new_followers", _bnum), "Comments": ("comments", _bnum),
    "Shares": ("shares", _bnum), "Likes": ("likes", _bnum)}


def _import_summary(rows):
    """Creator Live Performance export -> one row per stream (rich metrics)."""
    hi = next((i for i, r in enumerate(rows)
               if r and any(str(c).strip() == "Room ID" for c in r if c)), None)
    if hi is None:
        return {"error": "No 'Room ID' header in summary export."}
    hdr = [str(c).strip() if c is not None else "" for c in rows[hi]]

    def gi(n):
        return hdr.index(n) if n in hdr else None

    imported = 0
    for r in rows[hi + 1:]:
        if not r or not any(str(c).strip() for c in r if c is not None):
            continue
        sti = gi("Start Time")
        st = str(r[sti]) if (sti is not None and sti < len(r) and r[sti]) else ""
        m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", st)
        if not m:
            continue
        date, start_time = m.group(1), m.group(2)
        stream = {"date": date, "start_time": start_time}
        du = gi("Duration")
        if du is not None and du < len(r) and r[du]:
            dm = re.match(r"(?:(\d+)h)?(?:(\d+)m)?", str(r[du]))
            if dm:
                stream["duration_min"] = int(dm.group(1) or 0) * 60 + int(dm.group(2) or 0)
        for name, (field, fn) in _PERF_MAP.items():
            i = gi(name)
            if i is not None and i < len(r):
                stream[field] = fn(r[i])
        ri = gi("Room ID")
        if ri is not None and ri < len(r) and r[ri]:
            stream["room_id"] = str(r[ri])
        stream["products"] = _theme(stream.get("title"))
        ex = live_find_by_room(stream.get("room_id"))
        if not ex:
            con = db()
            row = con.execute("SELECT id FROM live_stream WHERE date=? AND "
                              "IFNULL(start_time,'')=IFNULL(?,'')",
                              (date, start_time)).fetchone()
            con.close()
            ex = row[0] if row else None
        if ex:
            live_delete(ex)
        live_save(stream)
        imported += 1
    return {"kind": "summary", "imported": imported}


def live_import_any(raw, filename=""):
    """Detect + import either export type from raw bytes (xlsx) or text (csv)."""
    try:
        if filename.lower().endswith(".csv"):
            text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
            sheets = {"performance_detail": list(csv.reader(io.StringIO(text)))}
        else:
            sheets = _xlsx_sheets(raw)
    except Exception as e:
        return {"error": f"Could not read the file: {e}"}
    for rows in sheets.values():
        for r in rows[:5]:
            if r and any(str(c).strip() == "Room Title" for c in r if c is not None):
                return _import_summary(rows)
    return _import_single(sheets)


def live_update_from_downloads():
    """Find the newest LIVE export in ~/Downloads and import it — the one-click
    'Update' button. Only works when the dashboard runs on the SAME Mac where the
    file was downloaded (the server reads its own ~/Downloads)."""
    dl = os.path.expanduser("~/Downloads")
    if not os.path.isdir(dl):
        return {"error": "No ~/Downloads folder found on the machine running the "
                         "dashboard."}
    cands = []
    for f in os.listdir(dl):
        low = f.lower()
        if not (low.endswith(".xlsx") or low.endswith(".csv")):
            continue
        if any(k in low for k in ("live", "dashboard", "creator", "performance")):
            p = os.path.join(dl, f)
            cands.append((os.path.getmtime(p), p, f))
    if not cands:
        return {"error": "No LIVE export found in ~/Downloads. On TikTok, hit the "
                         "download icon on the LIVE Board first, then press Update."}
    cands.sort(reverse=True)
    _, path, fname = cands[0]
    with open(path, "rb") as fh:
        res = live_import_any(fh.read(), fname)
    res["file"] = fname
    return res


PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QVC Opportunity Dashboard</title><style>
:root{--bg:#0d1117;--card:#161b22;--line:#30363d;--txt:#e6edf3;--dim:#8b949e;
--green:#3fb950;--blue:#58a6ff;--gold:#d29922}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,system-ui,sans-serif;
background:var(--bg);color:var(--txt);padding:16px;max-width:1200px;margin:0 auto}
h1{font-size:18px;margin:4px 0 14px}
.tabs{display:flex;gap:8px;margin-bottom:14px}
.tab{padding:8px 16px;border-radius:8px;background:var(--card);cursor:pointer;
border:1px solid var(--line);font-size:14px}
.tab.on{background:var(--blue);color:#fff;border-color:var(--blue)}
.panel{display:none}.panel.on{display:block}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px;margin-bottom:12px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:end}
label{font-size:11px;color:var(--dim);display:block;margin-bottom:3px}
input,select{background:var(--bg);color:var(--txt);border:1px solid var(--line);
border-radius:7px;padding:8px 10px;font-size:14px}
input[type=text]{min-width:220px}
button{background:var(--green);color:#04260f;font-weight:700;border:0;
border-radius:8px;padding:9px 18px;font-size:14px;cursor:pointer}
button.alt{background:var(--card);color:var(--txt);border:1px solid var(--line)}
#credits{float:right;color:var(--gold);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--dim);text-align:right;padding:7px 8px;cursor:pointer;
border-bottom:1px solid var(--line);white-space:nowrap;user-select:none}
td{padding:7px 8px;text-align:right;border-bottom:1px solid var(--line);
white-space:nowrap}
th:first-child,td:first-child{text-align:left;white-space:normal;min-width:220px}
tr:hover td{background:#1c2430}
.pc{color:var(--green);font-weight:700}.hot{color:var(--gold);font-weight:700}
.dim{color:var(--dim)}.spin{color:var(--dim);padding:20px;text-align:center}
.result{padding:10px;border-bottom:1px solid var(--line);cursor:pointer}
.result:hover{background:#1c2430}
.stat{display:inline-block;margin:6px 18px 6px 0}
.stat b{font-size:22px;display:block}
.stat span{font-size:11px;color:var(--dim)}
.err{color:#f85149;padding:10px}
.ok{color:var(--green);padding:6px 2px;font-size:13px}
.badge{border-radius:12px;padding:16px;margin-bottom:12px;text-align:center;
border:2px solid}
.badge .st{font-size:26px;font-weight:800;letter-spacing:.02em}
.badge .ph{font-size:12px;opacity:.85;margin-top:2px}
.badge ul{text-align:left;margin:10px 0 0;padding-left:20px;font-size:13px}
.b-stay{background:#0d2818;border-color:var(--green);color:#7ee2a8}
.b-swap{background:#2b220a;border-color:var(--gold);color:#f0c674}
.b-end{background:#2d1112;border-color:#f85149;color:#ff9d97}
.fgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
gap:10px}
.fgrid input,.fgrid textarea,.fgrid select{width:100%}
.fgrid textarea{background:var(--bg);color:var(--txt);border:1px solid var(--line);
border-radius:7px;padding:8px;font-size:14px;font-family:inherit;min-height:52px}
.fg-full{grid-column:1/-1}
.sec{font-size:12px;color:var(--blue);text-transform:uppercase;letter-spacing:.05em;
margin:14px 0 4px;grid-column:1/-1;border-bottom:1px solid var(--line);padding-bottom:3px}
.bar{display:flex;align-items:center;gap:8px;margin:3px 0;font-size:12px}
.bar .lab{width:110px;text-align:right;color:var(--dim);white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}
.bar .track{flex:1;background:#0d1117;border-radius:4px;height:16px;overflow:hidden}
.bar .fill{height:100%;background:var(--blue);border-radius:4px}
.bar .val{width:70px;color:var(--txt)}
.bm{font-size:11px;color:var(--dim);margin-left:6px}
@media(max-width:700px){td,th{padding:6px 5px;font-size:12px}
.badge .st{font-size:22px}.bar .lab{width:80px}}
</style></head><body>
<h1>QVC Opportunity Dashboard <span id="credits"></span></h1>
<div class="tabs">
<div class="tab on" data-p="scan">Shop Scanner</div>
<div class="tab" data-p="lookup">Product Lookup</div>
<div class="tab" data-p="live">Livestreams</div>
<div class="tab" data-p="livelog">🔴 LIVE Log</div>
</div>

<div class="panel on" id="scan">
<div class="card" style="border-color:var(--blue)">
<div style="font-size:13px;color:var(--dim);margin-bottom:9px">One-click views for the
selected shop (QVC by default) — no need to touch the filters below:</div>
<div class="row">
<button onclick="presetNew()">🆕 New this week</button>
<button onclick="presetMonth()">🗓️ New this month</button>
<button onclick="presetGems()">💎 Low-creator gems</button>
<button onclick="presetFewVideos()">📹 Fewest videos</button>
<button onclick="presetFewVideosDeep()">📹 Fewest videos (deep)</button>
<button onclick="presetFewCreators()">👥 Fewest creators</button>
<span class="dim" style="font-size:12px;align-self:center">New this week/month = listed in the
last 7/30 days. Gems = $1k–$25k revenue, ranked by $/creator. Fewest videos/creators = top 100
sellers ranked by least video/creator competition (a video-less seller = you'd be the only video
GMV Max can push). Deep = digs 500 products deep into the mid-tail (where smaller, uncontested
gems hide) and ranks the whole set by fewest videos. First run: ~$1 (top 100) / ~$5 (deep), then
cached &amp; free for 7 days.</span></div>
<div class="row" style="margin-top:8px">
<button class="alt" onclick="loadCache()">📁 Load cached results (free — no credits)</button>
<span class="dim" style="font-size:12px;align-self:center">Shows every product already in your
local cache, so you can Export CSV without spending. Works even at $0 balance.</span>
</div></div>
<div class="card"><div class="row">
<div><label>Shop</label><select id="shopSel">
<option value="7495811038271212487">QVC, Inc</option>
<option value="ALL">🌐 All shops (whole marketplace)</option></select></div>
<div><label>Find another shop</label>
<input type="text" id="shopKw" placeholder="shop name…" style="min-width:150px"></div>
<button class="alt" onclick="findShop()">Find</button>
<button class="alt" onclick="removeSavedShop()" title="Remove the selected saved shop from your permanent list">✕ Remove shop</button>
<div><label>Window</label><select id="win">
<option value="7">7 days</option><option value="30">30 days</option>
<option value="1">1 day</option></select></div>
<div><label>Detail top N</label><input type="number" id="topN" value="30"
style="width:70px"></div>
<div><label>Min units</label><input type="number" id="minU" value="50"
style="width:70px"></div>
<div><label>Launched</label><select id="launched">
<option value="">any time</option><option value="&lt;3">last 3 days</option>
<option value="&lt;7">last 7 days</option>
<option value="&lt;30">last 30 days</option></select></div>
<div><label>Pages (100/pg)</label><select id="pages">
<option value="1">1</option><option value="2">2</option>
<option value="3">3</option><option value="5">5</option></select></div>
<div><label>Rev min $</label><input type="number" id="revMin" placeholder="any"
style="width:80px"></div>
<div><label>Rev max $</label><input type="number" id="revMax" placeholder="any"
style="width:80px"></div>
<button onclick="runScan(false)">Run Scan</button>
<button class="alt" onclick="runScan(true)">Force-refresh details</button>
</div><div id="shopResults"></div></div>
<div class="card" id="scanOut"><div class="dim">Run a scan — cached details are
free, new ones cost ~1&cent; each.</div></div>
</div>

<div class="panel" id="lookup">
<div class="card"><div class="row">
<div><label>Product name</label>
<input type="text" id="prodKw" placeholder="e.g. panini grill"
onkeydown="if(event.key==='Enter')findProd()"></div>
<div><label>Within shop</label><select id="shopL">
<option value="">All shops</option>
<option value="7495811038271212487">QVC, Inc</option></select></div>
<div><label>Window</label><select id="winL">
<option value="7">7 days</option><option value="30">30 days</option></select></div>
<button onclick="findProd()">Search</button>
</div></div>
<div class="card"><div class="row">
<div><label>Gem hunt rev min $</label><input type="number" id="hRevMin"
value="1000" style="width:80px"></div>
<div><label>Rev max $</label><input type="number" id="hRevMax" value="25000"
style="width:80px"></div>
<div><label>Min units</label><input type="number" id="hMinU" value="10"
style="width:70px"></div>
<div><label>Detail top N</label><input type="number" id="hTop" value="40"
style="width:70px"></div>
<button onclick="runHunt()">Gem Hunt this keyword</button>
</div><div class="dim" style="margin-top:6px;font-size:12px">Pulls up to 200
products matching the keyword across ALL shops, keeps the revenue band, loads
creator counts, ranks by $/creator. ~2&cent; + 1&cent; per detailed product.</div></div>
<div class="card" id="huntOut" style="display:none"></div>
<div class="card" id="prodResults" style="display:none"></div>
<div class="card" id="prodDetail" style="display:none"></div>
</div>

<div class="panel" id="live">
<div class="card"><div class="row">
<div><label>Shop</label><select id="lsShop">
<option value="7495811038271212487">QVC, Inc</option>
<option value="ALL">🌐 All shops (whole marketplace)</option></select></div>
<div><label>Window</label><select id="lsWin">
<option value="7">7 days</option><option value="30">30 days</option>
<option value="1">1 day</option></select></div>
<div><label>&nbsp;</label><label style="font-size:13px;color:var(--txt)">
<input type="checkbox" id="lsHideOfficial" checked> Hide the shop's own accounts</label></div>
<button onclick="runLive()">Find livestreams</button>
</div><div class="dim" style="font-size:12px;margin-top:6px">Top livestreams selling this
shop's products, ranked by revenue — see which affiliates are live-selling its gear and how
well. Tap a creator to open their TikTok. ~1&cent; per run.</div></div>
<div class="card" id="liveOut"><div class="dim">Find livestreams to see who's live-selling
this shop's products.</div></div>
</div>

<div class="panel" id="livelog">
<div class="card" style="border-color:#f85149">
<div class="row">
<button onclick="llUpdate()">⚡ Update from latest download</button>
<button class="alt" onclick="llShowList()">📋 All streams</button>
<button class="alt" onclick="llTrends()">📈 Trends</button>
<button class="alt" onclick="llNew()">➕ New (manual)</button>
<label class="alt" style="padding:9px 14px;border-radius:8px;border:1px solid var(--line);cursor:pointer">
📥 Pick a file<input type="file" id="llCsv" accept=".xlsx,.csv" style="display:none" onchange="llImportFile(this)"></label>
</div>
<div class="dim" style="font-size:12px;margin-top:6px"><b>Fastest way, no typing:</b> on TikTok hit the
download icon on the LIVE Board, then come here and hit <b>⚡ Update from latest download</b> — it grabs the
newest export from your Downloads, loads the whole curve, and shows the STAY/SWAP/END badge. (Works when the
dashboard runs on the same Mac you downloaded on.) On another machine, use <b>📥 Pick a file</b> instead.
Costs ZERO Kalodata credits.</div>
</div>
<div id="llView"><div class="card"><div class="spin">Loading…</div></div></div>
</div>

<script>
const $=id=>document.getElementById(id);
document.querySelectorAll('.tab').forEach(t=>t.onclick=()=>{
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('on'));
  document.querySelectorAll('.panel').forEach(x=>x.classList.remove('on'));
  t.classList.add('on');$(t.dataset.p).classList.add('on');
  if(t.dataset.p==='livelog'&&!llLoaded){llLoaded=true;llShowList();}});
async function post(u,b){const r=await fetch(u,{method:'POST',
  headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
  const j=await r.json();
  if(j.credits_used!==undefined)$('credits').textContent=
    'session: '+j.credits_used.toFixed(1)+' credits (~$'+(j.credits_used*0.1).toFixed(2)+')';
  if(j.error)throw new Error(j.error);return j;}
const fmt=n=>n==null?'—':n.toLocaleString();
const money=n=>n==null?'—':'$'+Math.round(n).toLocaleString();

async function findShop(){const kw=$('shopKw').value.trim();if(!kw)return;
  $('shopResults').innerHTML='<div class="spin">searching…</div>';
  try{const j=await post('/api/shops',{keyword:kw});
    $('shopResults').innerHTML=j.data.map(s=>
      `<div class="result" onclick="addShop('${s.shop_id}',
       '${(s.shop_name||'').replace(/'/g,'')}')">${s.shop_name}
       <span class="dim"> — ${money(s.revenue)} rev, ${fmt(s.sales_volumn)}
       units (7d)</span></div>`).join('')||'<div class="dim">no matches</div>';
  }catch(e){$('shopResults').innerHTML='<div class="err">'+e.message+'</div>';}}
function ensureOption(sel,id,name){
  for(const o of sel.options){if(o.value===id)return;}
  const o=document.createElement('option');o.value=id;o.textContent=name;sel.appendChild(o);}
function addShop(id,name){
  ensureOption($('shopSel'),id,name);ensureOption($('shopL'),id,name);ensureOption($('lsShop'),id,name);
  $('shopSel').value=id;$('shopResults').innerHTML='';
  post('/api/save_shop',{shop_id:id,shop_name:name}).catch(()=>{});}
async function loadSavedShops(){
  try{const j=await post('/api/saved_shops',{});
    (j.data||[]).forEach(s=>{ensureOption($('shopSel'),s.shop_id,s.shop_name);
      ensureOption($('shopL'),s.shop_id,s.shop_name);ensureOption($('lsShop'),s.shop_id,s.shop_name);});
  }catch(e){}}
async function removeSavedShop(){
  const sel=$('shopSel'),id=sel.value,name=sel.options[sel.selectedIndex].text;
  if(id==='7495811038271212487'||id==='ALL'){alert('That one is built in — cannot remove it.');return;}
  if(!confirm('Remove "'+name+'" from your saved shops?'))return;
  try{await post('/api/remove_shop',{shop_id:id});}catch(e){}
  for(const s of ['shopSel','shopL','lsShop']){const el=$(s);
    for(const o of [...el.options]){if(o.value===id)o.remove();}}
  $('shopSel').value='7495811038271212487';}
loadSavedShops();

function renderLive(rows){
  if(!rows.length){$('liveOut').innerHTML='<div class="dim">No livestreams found for this shop/window.</div>';return;}
  $('liveOut').innerHTML='<table><tr><th>Creator</th><th>Revenue</th><th>Views</th>'+
    '<th>Avg price</th><th>Mins</th><th>Title</th></tr>'+rows.map(r=>{
    const h=(r.creator_handle||'').replace(/[^a-zA-Z0-9._]/g,'');
    return '<tr><td><a href="https://www.tiktok.com/@'+h+'" target="_blank">@'+
      (r.creator_handle||'?')+'</a></td><td class="pc">'+money(r.revenue)+'</td>'+
      '<td>'+fmt(r.views)+'</td><td>'+money(r.unit_price)+'</td>'+
      '<td class="dim">'+r.duration_min+'</td><td>'+(r.title||'')+'</td></tr>';}).join('')+'</table>';}
async function runLive(){
  $('liveOut').innerHTML='<div class="spin">Loading livestreams…</div>';
  try{const j=await post('/api/livestreams',{shop_id:$('lsShop').value,window:+$('lsWin').value});
    let data=j.data||[];
    if($('lsHideOfficial').checked){
      const sel=$('lsShop'),nm=(sel.options[sel.selectedIndex].text||'').toLowerCase();
      const m=nm.match(/[a-z0-9]+/),token=m?m[0]:'';
      if(token&&token!=='all')
        data=data.filter(r=>!String(r.creator_handle||'').toLowerCase().includes(token));}
    renderLive(data);
  }catch(e){$('liveOut').innerHTML='<div class="err">'+e.message+'</div>';}}

function presetNew(){
  $('win').value='7';$('launched').value='<7';$('minU').value='1';
  $('topN').value='30';$('pages').value='1';
  $('revMin').value='';$('revMax').value='';
  runScan(false);}
function presetMonth(){
  $('win').value='30';$('launched').value='<30';$('minU').value='1';
  $('topN').value='40';$('pages').value='1';
  $('revMin').value='';$('revMax').value='';
  runScan(false);}
function presetGems(){
  $('win').value='7';$('launched').value='';$('minU').value='10';
  $('topN').value='40';$('pages').value='3';
  $('revMin').value='1000';$('revMax').value='25000';
  runScan(false);}
function presetFewVideos(){
  $('win').value='7';$('launched').value='';$('minU').value='1';
  $('topN').value='100';$('pages').value='1';
  $('revMin').value='';$('revMax').value='';
  runScan(false,'videos');}
function presetFewVideosDeep(){
  $('win').value='7';$('launched').value='';$('minU').value='10';
  $('topN').value='500';$('pages').value='5';
  $('revMin').value='';$('revMax').value='';
  runScan(false,'videos');}
function presetFewCreators(){
  $('win').value='7';$('launched').value='';$('minU').value='1';
  $('topN').value='100';$('pages').value='1';
  $('revMin').value='';$('revMax').value='';
  runScan(false,'creators');}

async function scanCall(body){
  // Runs a scan, but if the server says it would cost >25c, show the exact
  // price (only counts NEW/uncached products) and wait for OK/Cancel first.
  let j=await post('/api/scan',body);
  const e=j.data;
  if(e&&e.needs_confirm){
    const credits=(e.n_new*0.1).toFixed(1);
    if(!confirm('Cost to run: about '+credits+' credits ($'+e.estimate.toFixed(2)+
      '). That is '+e.n_new+' new products at 0.1 credit (~1 cent) each'+
      (e.n_cached?'; '+e.n_cached+' already cached are free':'')+'. Continue?'))
      return null;
    j=await post('/api/scan',Object.assign({},body,{confirmed:true}));
  }
  return j;}
async function runScan(refresh,sort){
  sort=sort||'per_creator';
  $('scanOut').innerHTML='<div class="spin">Scanning… detail calls take a few '+
   'seconds each the first time. Cached ones are instant.</div>';
  try{const j=await scanCall({shop_id:$('shopSel').value,
    window:+$('win').value,top:+$('topN').value,min_units:+$('minU').value,
    pages:+$('pages').value,rev_min:$('revMin').value,rev_max:$('revMax').value,
    launched:$('launched').value||undefined,refresh:refresh,sort:sort});
  if(!j){$('scanOut').innerHTML='<div class="dim">Cancelled — nothing spent.</div>';return;}
  if(sort==='videos'){sortKey='videos';sortAsc=true;}
  else if(sort==='creators'){sortKey='creators';sortAsc=true;}
  else{sortKey='per_creator';sortAsc=false;}
  renderTable(j.data);}catch(e){
    $('scanOut').innerHTML='<div class="err">'+e.message+'</div>';}}

let rows=[],sortKey='per_creator',sortAsc=false,tableTarget='scanOut',lastSorted=[];
async function loadCache(){
  $('scanOut').innerHTML='<div class="spin">Loading cached results (no credits)…</div>';
  try{const j=await post('/api/cache',{});
    if(!j.data.length){$('scanOut').innerHTML='<div class="dim">Nothing cached yet — '+
      'run a scan first (needs credits), then this pulls it back for free.</div>';return;}
    sortKey='videos';sortAsc=true;renderTable(j.data);
  }catch(e){$('scanOut').innerHTML='<div class="err">'+e.message+'</div>';}}
function renderTable(data,target){rows=data;tableTarget=target||'scanOut';draw();}
function draw(){
  const cols=[['name','Product'],['units','Units'],['creators','Creators'],
   ['per_creator','$/Creator'],['pool','Pool $'],['units_per_creator','U/Cr'],
   ['videos','Vids'],['lives','Lives'],['revenue','Revenue'],
   ['card_rev','Card $'],['ad_pct','Ad %'],['price','Price'],
   ['commission_pct','Comm%'],['growth_pct','Growth%']];
  const sorted=[...rows].sort((a,b)=>{
    const x=a[sortKey],y=b[sortKey];
    if(x==null)return 1;if(y==null)return -1;
    return sortAsc?(x>y?1:-1):(x<y?1:-1);});
  lastSorted=sorted;
  $(tableTarget).innerHTML='<div style="margin-bottom:8px">'+
    '<button class="alt" onclick="exportCSV()">⬇ Export CSV ('+sorted.length+' rows)</button>'+
    '</div><table><tr>'+cols.map(c=>
    `<th onclick="setSort('${c[0]}')">${c[1]}${sortKey===c[0]?(sortAsc?' ▲':' ▼'):''}</th>`)
    .join('')+'</tr>'+sorted.map(r=>`<tr>
    <td>${r.name}</td><td>${fmt(r.units)}</td>
    <td class="${r.creators!=null&&r.creators<25?'hot':''}">${fmt(r.creators)}</td>
    <td class="pc">${r.per_creator!=null?money(r.per_creator):'—'}</td>
    <td>${money(r.pool)}</td><td>${r.units_per_creator??'—'}</td>
    <td class="dim">${fmt(r.videos)}</td><td class="dim">${fmt(r.lives)}</td>
    <td>${money(r.revenue)}</td>
    <td>${money(r.card_rev)}</td>
    <td class="${(r.ad_pct||0)>60?'hot':'dim'}">${r.ad_pct??'—'}</td>
    <td>${money(r.price)}</td>
    <td>${r.commission_pct??'—'}</td>
    <td class="${(r.growth_pct||0)>50?'hot':'dim'}">${r.growth_pct??'—'}</td>
    </tr>`).join('')+'</table>';}
function setSort(k){if(sortKey===k)sortAsc=!sortAsc;else{sortKey=k;sortAsc=false;}draw();}
function exportCSV(){
  if(!lastSorted.length){alert('Run a scan first — nothing to export yet.');return;}
  const cols=[['product_id','Product ID'],['name','Product'],['units','Units'],
   ['creators','Creators'],['per_creator','$/Creator'],['pool','Pool $'],
   ['units_per_creator','Units/Creator'],['videos','Videos'],['lives','Lives'],
   ['revenue','Revenue'],['card_rev','Card Rev'],['ad_pct','Ad %'],['price','Price'],
   ['commission_pct','Commission %'],['growth_pct','Growth %'],['launch_date','Launched']];
  const esc=v=>{if(v==null)return '';v=String(v);
    return /[",\\n]/.test(v)?'"'+v.replace(/"/g,'""')+'"':v;};
  const csv=cols.map(c=>c[1]).join(',')+'\\n'+
    lastSorted.map(r=>cols.map(c=>esc(r[c[0]])).join(',')).join('\\n');
  const a=document.createElement('a');
  a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
  a.download='kalodata_'+new Date().toISOString().slice(0,10)+'.csv';
  document.body.appendChild(a);a.click();document.body.removeChild(a);
  URL.revokeObjectURL(a.href);}

async function runHunt(){const kw=$('prodKw').value.trim();
  if(!kw){alert('Type a keyword in the Product name box first');return;}
  $('huntOut').style.display='block';
  $('prodResults').style.display='none';$('prodDetail').style.display='none';
  $('huntOut').innerHTML='<div class="spin">Hunting "'+kw+'" across all shops... '+
    'first run takes a minute (detail calls). Cached ones are instant.</div>';
  try{const j=await scanCall({keyword:kw,window:+$('winL').value,
    top:+$('hTop').value,min_units:+$('hMinU').value,pages:2,
    rev_min:$('hRevMin').value,rev_max:$('hRevMax').value,refresh:false});
    if(!j){$('huntOut').innerHTML='<div class="dim">Cancelled — nothing spent.</div>';return;}
    renderTable(j.data,'huntOut');
  }catch(e){$('huntOut').innerHTML='<div class="err">'+e.message+'</div>';}}

async function findProd(){const kw=$('prodKw').value.trim();if(!kw)return;
  $('prodResults').style.display='block';$('prodDetail').style.display='none';
  $('prodResults').innerHTML='<div class="spin">searching…</div>';
  try{const j=await post('/api/product',{keyword:kw,window:+$('winL').value,
    shop_id:$('shopL').value||undefined});
    lastResults=j.data;
    $('prodResults').innerHTML=(j.data.length?
      '<div style="margin-bottom:8px"><button class="alt" onclick="loadCreators()">'+
      'Load creator counts for all ('+j.data.length+' results, ~'+j.data.length+
      '&cent;)</button></div>':'')+
      (j.data.map(p=>
      `<div class="result" onclick="showDetail('${p.product_id}')">
       ${p.product_name}<span class="dim"> — ${money(p.revenue)} rev,
       ${fmt(p.sales_volumn)} units, ${p.commission_rate??'—'}% comm</span>`+
       `<span class="hot" id="cr_${p.product_id}"></span></div>`)
      .join('')||'<div class="dim">no matches</div>');
  }catch(e){$('prodResults').innerHTML='<div class="err">'+e.message+'</div>';}}

let lastResults=[];
async function loadCreators(){
  for(const p of lastResults){
    const el=$('cr_'+p.product_id);
    if(!el||el.textContent)continue;
    el.textContent=' ...';
    try{const j=await post('/api/detail',{product_id:p.product_id,
      window:+$('winL').value});
      const d=j.data,rate=(d.commission_rate||0)/100,
        pc=d.creator_number?Math.round((d.revenue||0)*rate/d.creator_number):null;
      el.textContent=' \u2022 '+fmt(d.creator_number)+' creators'+
        (pc!=null?' \u2022 '+money(pc)+'/creator':'');
    }catch(e){el.textContent=' \u2022 ?';}
  }}

async function showDetail(pid){
  $('prodDetail').style.display='block';
  $('prodDetail').innerHTML='<div class="spin">loading detail…</div>';
  try{const j=await post('/api/detail',{product_id:pid,window:+$('winL').value});
    const d=j.data,rate=(d.commission_rate||0)/100,
      pool=Math.round((d.revenue||0)*rate),
      pc=d.creator_number?Math.round(pool/d.creator_number):null;
    $('prodDetail').innerHTML=`<h3 style="margin:0 0 8px">${d.product_name}</h3>
    <div class="stat"><b class="pc">${pc!=null?money(pc):'—'}</b>
      <span>$/creator</span></div>
    <div class="stat"><b class="${d.creator_number<25?'hot':''}">${fmt(d.creator_number)}</b><span>creators</span></div>
    <div class="stat"><b>${fmt(d.video_number)}</b><span>videos</span></div>
    <div class="stat"><b>${fmt(d.live_number)}</b><span>lives</span></div>
    <div class="stat"><b>${fmt(d.sales_volumn)}</b><span>units</span></div>
    <div class="stat"><b>${money(d.revenue)}</b><span>revenue</span></div>
    <div class="stat"><b>${money(pool)}</b><span>commission pool</span></div>
    <div class="stat"><b>${d.commission_rate??'—'}%</b><span>commission</span></div>
    <div class="stat"><b>${money(d.min_price)}</b><span>price</span></div>
    <div class="stat"><b>${money(d.video_revenue)}</b><span>video rev</span></div>
    <div class="stat"><b>${money(d.live_revenue)}</b><span>live rev</span></div>
    <div class="stat"><b>${d.launch_date??'—'}</b><span>launched</span></div>`;
  }catch(e){$('prodDetail').innerHTML='<div class="err">'+e.message+'</div>';}}

/* ===================== LIVE Log ===================== */
let llLoaded=false,llLast=null;
function escHtml(s){return String(s==null?'':s).replace(/&/g,'&amp;')
  .replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function escAttr(s){return escHtml(s).replace(/"/g,'&quot;');}
function llV(k){const el=$('lf_'+k);return el?el.value.trim():'';}
const LL_FIELDS=[
 ['sec','Basics'],
 ['date','Date','date'],['start_time','Start time','time'],
 ['duration_min','Duration (min)','num'],['title','Title','text','full'],
 ['products','Products (comma-separated)','text','full'],
 ['sec','Traffic'],
 ['impressions','Impressions','num'],['unique_viewers','Unique viewers','num'],
 ['join_rate','Join rate (0-1)','num'],['peak_concurrent','Peak concurrent','num'],
 ['avg_concurrent','Avg concurrent','num'],['avg_watch_sec','Avg watch (sec)','num'],
 ['fyp_pct','For You %','num'],['following_pct','Following %','num'],
 ['sec','Engagement'],
 ['comments','Comments','num'],['likes','Likes','num'],
 ['shares','Shares','num'],['new_followers','New followers','num'],
 ['sec','Product & sales'],
 ['product_clicks','Product clicks','num'],['ctr','Product CTR (0-1)','num'],
 ['cto','Click-to-order (0-1)','num'],['orders','Orders','num'],
 ['gmv','GMV $','num'],['est_commission','Est commission $','num'],
 ['aov','AOV $ (auto if blank)','num'],['gpm','GPM (auto if blank)','num'],
 ['sec','Notes & post-stream loop'],
 ['pcv_note','Peak-concurrent moment — what were you doing?','area','full'],
 ['debrief','Debrief — top moments, tech issues, unanswered questions','area','full'],
 ['improved_metric','1 metric that IMPROVED (double down)','text','full'],
 ['declined_metric','1 metric that DECLINED (diagnose)','text','full'],
 ['next_test','1 single-variable test for next time','text','full']];
function llFormHtml(d){
  d=d||{};
  return '<div class="fgrid">'+LL_FIELDS.map(f=>{
    if(f[0]==='sec')return '<div class="sec">'+f[1]+'</div>';
    const key=f[0],label=f[1],type=f[2],full=f[3]==='full'?'fg-full':'';
    const v=d[key]==null?'':d[key];
    if(type==='area')
      return '<div class="'+full+'"><label>'+label+'</label><textarea id="lf_'+key+'">'+escHtml(v)+'</textarea></div>';
    let t='text';if(type==='date')t='date';else if(type==='time')t='time';
    let extra=type==='num'?' step="any" inputmode="decimal"':'';
    if(type==='num')t='number';
    return '<div class="'+full+'"><label>'+label+'</label><input type="'+t+'"'+extra+
      ' id="lf_'+key+'" value="'+escAttr(v)+'"></div>';
  }).join('')+'</div>';}
function llCollect(){const o={};LL_FIELDS.forEach(f=>{
  if(f[0]==='sec')return;o[f[0]]=llV(f[0]);});return o;}

async function llShowList(){
  $('llView').innerHTML='<div class="card"><div class="spin">Loading streams…</div></div>';
  try{const j=await post('/api/live/list',{});const rows=j.data||[];
    if(!rows.length){$('llView').innerHTML='<div class="card"><div class="dim">'+
      'No streams logged yet. Hit <b>➕ New stream</b> after (or during) a live, or '+
      '<b>📥 Import CSV</b> a Creator Live Performance export.</div></div>';return;}
    const h='<div class="card"><table><tr><th>Date</th><th>Start</th><th>Min</th>'+
      '<th>GMV</th><th>Orders</th><th>GPM</th><th>AWT</th><th>C/Ord</th><th>Title</th></tr>'+
      rows.map(r=>'<tr style="cursor:pointer" onclick="llDetail('+r.id+')">'+
        '<td style="text-align:left">'+escHtml(r.date||'')+' <span class="dim">'+(r.weekday||'')+'</span></td>'+
        '<td>'+escHtml(r.start_time||'—')+'</td><td class="dim">'+fmt(r.duration_min)+'</td>'+
        '<td class="pc">'+money(r.gmv)+'</td><td>'+fmt(r.orders)+'</td>'+
        '<td>'+(r.gpm==null?'—':Math.round(r.gpm))+'</td>'+
        '<td class="'+awtCls(r.avg_watch_sec)+'">'+(r.avg_watch_sec==null?'—':r.avg_watch_sec+'s')+'</td>'+
        '<td class="'+cpoCls(r.comments_per_order)+'">'+(r.comments_per_order==null?'—':r.comments_per_order)+'</td>'+
        '<td style="text-align:left">'+escHtml(r.title||'')+'</td></tr>').join('')+'</table></div>';
    $('llView').innerHTML=h;
  }catch(e){$('llView').innerHTML='<div class="card"><div class="err">'+e.message+'</div></div>';}}
function awtCls(s){if(s==null)return 'dim';if(s<90)return 'err';if(s>180)return 'pc';return '';}
function cpoCls(c){if(c==null)return 'dim';if(c>50||c<10)return 'hot';return 'pc';}

async function llNew(){
  let carry='';
  try{const j=await post('/api/live/list',{});const rows=j.data||[];
    const last=rows.find(r=>r.next_test);
    if(last)carry='<div class="card" style="border-color:var(--gold)"><b>Last stream test to run:</b> '+
      escHtml(last.next_test)+'</div>';}catch(e){}
  const today=new Date().toISOString().slice(0,10);
  const now=new Date().toTimeString().slice(0,5);
  $('llView').innerHTML=carry+'<div class="card"><h3 style="margin:0 0 4px">New stream</h3>'+
    llFormHtml({date:today,start_time:now})+
    '<div class="row" style="margin-top:12px"><button onclick="llSave(0)">Save stream</button>'+
    '<button class="alt" onclick="llShowList()">Cancel</button></div></div>';}

async function llSave(id){
  const o=llCollect();if(id)o.id=id;
  try{const j=await post('/api/live/save',o);
    const nid=(j.data&&j.data.id)||id;
    if(nid)llDetail(nid);else llShowList();
  }catch(e){alert('Save failed: '+e.message);}}

async function llDetail(id){
  $('llView').innerHTML='<div class="card"><div class="spin">Loading…</div></div>';
  try{const j=await post('/api/live/get',{id:id});const d=j.data;
    if(!d||d.error){$('llView').innerHTML='<div class="card"><div class="err">Not found</div></div>';return;}
    llLast=d;
    const dec=d.decision||{},ci=d.checkins||[],s=d.stream||{};
    const cls=dec.status==='STAY'?'b-stay':(dec.status&&dec.status.indexOf('END')===0?'b-end':'b-swap');
    const nextMin=ci.length?(ci[ci.length-1].minute||0)+15:15;
    const badge='<div class="badge '+cls+'"><div class="st">'+(dec.status||'STAY')+'</div>'+
      '<div class="ph">Phase: '+(dec.phase||'—')+(dec.minute!=null?'  ·  minute '+dec.minute:'')+'</div>'+
      '<ul>'+(dec.reasons||[]).map(r=>'<li>'+escHtml(r)+'</li>').join('')+'</ul></div>';
    // quick check-in form (one screen)
    const ck='<div class="card" style="border-color:var(--blue)">'+
      '<div style="font-weight:700;margin-bottom:8px">➕ 15-min check-in</div>'+
      '<div class="fgrid">'+
      ciIn('minute','Minute',nextMin)+ciIn('entries','New entries','')+
      ciIn('concurrent','Concurrent','')+ciIn('comments','Comments (since)','')+
      ciIn('product_clicks','Product clicks','')+ciIn('orders','Orders (since)','')+
      ciIn('gmv','GMV (since) $','')+
      '<div><label>Pinned product</label><input type="text" id="ci_pinned_product"></div>'+
      '<div class="fg-full"><label>Note</label><input type="text" id="ci_note"></div>'+
      '</div><div class="row" style="margin-top:10px">'+
      '<button onclick="llCheckin('+id+')">Log check-in</button></div></div>';
    // timeline
    let tl='<div class="card"><div style="font-weight:700;margin-bottom:6px">Check-in timeline</div>';
    if(!ci.length)tl+='<div class="dim">No check-ins yet. Log one every 15 min during the stream.</div>';
    else{tl+='<table><tr><th>Min</th><th>Entries</th><th>Conc.</th><th>Comm.</th>'+
      '<th>Clicks</th><th>Orders</th><th>GMV</th><th>Pin</th><th>Note</th></tr>'+
      ci.map(c=>'<tr><td>'+fmt(c.minute)+'</td><td>'+fmt(c.entries)+'</td>'+
        '<td>'+fmt(c.concurrent)+'</td><td>'+fmt(c.comments)+'</td>'+
        '<td>'+fmt(c.product_clicks)+'</td><td>'+fmt(c.orders)+'</td>'+
        '<td class="pc">'+money(c.gmv)+'</td><td style="text-align:left">'+escHtml(c.pinned_product||'')+'</td>'+
        '<td style="text-align:left">'+escHtml(c.note||'')+'</td></tr>').join('')+'</table>';
      tl+='<div class="sec" style="border:0">Concurrent</div>'+
        bars(ci.map(c=>({k:'m'+c.minute,v:c.concurrent||0})));
      tl+='<div class="sec" style="border:0">Entries</div>'+
        bars(ci.map(c=>({k:'m'+c.minute,v:c.entries||0})));
      tl+='<div class="sec" style="border:0">GMV per check-in</div>'+
        bars(ci.map(c=>({k:'m'+c.minute,v:c.gmv||0})),money);}
    tl+='</div>';
    // stream summary metrics with benchmarks
    const sm='<div class="card"><div style="font-weight:700;margin-bottom:6px">Stream metrics</div>'+
      statLine('GPM',s.gpm==null?'—':Math.round(s.gpm),'buys reach')+
      statLine('Avg watch',s.avg_watch_sec==null?'—':s.avg_watch_sec+'s',awtBench(s.avg_watch_sec))+
      statLine('Product CTR',pct(s.ctr),(s.ctr!=null&&s.ctr<0.03)?'&lt;3% → fix pin/CTA':'≥3% ok')+
      statLine('Click-to-order',pct(s.cto),'')+
      statLine('AOV',money(s.aov),'lead higher-ticket to lift')+
      statLine('Comments/order',s.comments_per_order==null?'—':s.comments_per_order,cpoBench(s.comments_per_order))+
      statLine('For You %',s.fyp_pct==null?'—':s.fyp_pct+'%',(s.fyp_pct!=null&&s.fyp_pct>40)?'earning reach':'&gt;40% target')+
      statLine('Orders/hr',s.orders_per_hour==null?'—':s.orders_per_hour,'')+
      statLine('GMV/hr',money(s.gmv_per_hour),'')+'</div>';
    // edit form
    const ef='<div class="card"><div style="font-weight:700;margin-bottom:6px">Edit stream</div>'+
      llFormHtml(s)+'<div class="row" style="margin-top:12px">'+
      '<button onclick="llSave('+id+')">Save changes</button>'+
      '<button class="alt" onclick="llShowList()">← All streams</button>'+
      '<button class="alt" style="color:#f85149" onclick="llDelete('+id+')">Delete</button></div></div>';
    $('llView').innerHTML=badge+ck+tl+sm+ef;
  }catch(e){$('llView').innerHTML='<div class="card"><div class="err">'+e.message+'</div></div>';}}
function ciIn(k,label,val){return '<div><label>'+label+'</label><input type="number" step="any" '+
  'inputmode="decimal" id="ci_'+k+'" value="'+escAttr(val)+'"></div>';}
function statLine(k,v,note){return '<div style="padding:4px 0;border-bottom:1px solid var(--line)">'+
  '<span class="dim" style="display:inline-block;width:130px">'+k+'</span>'+
  '<b>'+v+'</b>'+(note?'<span class="bm">'+note+'</span>':'')+'</div>';}
function pct(x){return x==null?'—':(x*100).toFixed(1)+'%';}
function awtBench(s){if(s==null)return '';if(s<90)return '&lt;90s structural problem';
  if(s>180)return '&gt;3min sweet spot';return '90s-3min optimize';}
function cpoBench(c){if(c==null)return '';if(c>50)return '&gt;50 hollow';
  if(c<10)return '&lt;10 under-engaged';return '15-30 healthy';}
function bars(items,fmtv){
  if(!items.length)return '<div class="dim">No data.</div>';
  const max=Math.max.apply(null,items.map(i=>i.v||0).concat([1]));
  return items.map(i=>'<div class="bar"><span class="lab">'+escHtml(i.k)+'</span>'+
    '<span class="track"><span class="fill" style="width:'+Math.round((i.v||0)/max*100)+'%"></span></span>'+
    '<span class="val">'+(fmtv?fmtv(i.v):fmt(i.v))+'</span></div>').join('');}

async function llCheckin(id){
  const o={stream_id:id};
  ['minute','entries','concurrent','comments','product_clicks','orders','gmv','pinned_product','note']
    .forEach(k=>{const el=$('ci_'+k);if(el)o[k]=el.value.trim();});
  try{await post('/api/live/checkin',o);llDetail(id);
  }catch(e){alert('Check-in failed: '+e.message);}}

async function llDelete(id){
  if(!confirm('Delete this stream and its check-ins?'))return;
  try{await post('/api/live/delete',{id:id});llShowList();
  }catch(e){alert('Delete failed: '+e.message);}}

function llImportResult(d){
  if(!d||d.error){$('llView').innerHTML='<div class="card"><div class="err">'+
    ((d&&d.error)||'Import failed')+'</div></div>';return;}
  if(d.kind==='summary'){
    alert('Imported '+d.imported+' stream(s) from '+(d.file||'the file')+'.');
    llShowList();return;}
  // single stream -> jump to its detail so the badge + curve show
  const tag=d.merged?'Updated':'Loaded';
  llDetail(d.id);
  setTimeout(()=>{const b=document.querySelector('#llView .badge');
    if(b)b.scrollIntoView({behavior:'smooth',block:'center'});},150);
  console.log(tag+' stream '+d.id+': $'+d.gmv+', '+d.orders+' orders, '+d.checkins+' check-ins');}
function toB64(buf){const bytes=new Uint8Array(buf);let bin='';const CH=0x8000;
  for(let i=0;i<bytes.length;i+=CH){bin+=String.fromCharCode.apply(null,bytes.subarray(i,i+CH));}
  return btoa(bin);}
async function llImportFile(input){
  const file=input.files&&input.files[0];if(!file)return;
  const buf=await file.arrayBuffer();input.value='';
  $('llView').innerHTML='<div class="card"><div class="spin">Reading '+escHtml(file.name)+'…</div></div>';
  try{const j=await post('/api/live/import_file',{filename:file.name,b64:toB64(buf)});
    llImportResult(j.data);
  }catch(e){$('llView').innerHTML='<div class="card"><div class="err">'+e.message+'</div></div>';}}
async function llUpdate(){
  $('llView').innerHTML='<div class="card"><div class="spin">Grabbing the latest export from '+
    'your Downloads…</div></div>';
  try{const j=await post('/api/live/update_downloads',{});
    if(j.data&&!j.data.error&&j.data.file)
      console.log('Imported from '+j.data.file);
    llImportResult(j.data);
  }catch(e){$('llView').innerHTML='<div class="card"><div class="err">'+e.message+'</div></div>';}}

async function llTrends(){
  $('llView').innerHTML='<div class="card"><div class="spin">Crunching trends…</div></div>';
  try{const j=await post('/api/live/trends',{});const t=j.data||{};
    if(!t.n_streams){$('llView').innerHTML='<div class="card"><div class="dim">No streams yet.</div></div>';return;}
    let h='<div class="card"><div style="font-weight:700">Across '+t.n_streams+' stream(s)</div>'+
      '<div class="dim" style="font-size:12px">After ~10 streams, expect 3-4 metrics to move. '+
      'If &gt;80% of GMV lands in one 20-30 min window most streams, go shorter &amp; more frequent.</div></div>';
    h+='<div class="card"><div class="sec" style="border:0">GMV by start hour</div>'+
      bars((t.by_hour||[]).map(x=>({k:x.k+':00',v:x.v})),money)+
      '<div class="sec">GMV by weekday</div>'+
      bars((t.by_weekday||[]).map(x=>({k:x.k,v:x.v})),money)+
      '<div class="sec">GMV by product</div>'+
      bars((t.by_product||[]).map(x=>({k:x.k,v:x.v})),money)+'</div>';
    const ser=t.series||[];
    h+='<div class="card"><div class="sec" style="border:0">Metric trend (oldest → newest)</div>'+
      '<table><tr><th>Stream</th><th>GPM</th><th>AWT</th><th>CTR</th><th>C_O</th>'+
      '<th>Ord/hr</th><th>PCV</th><th>GMV</th></tr>'+
      ser.map(r=>'<tr><td style="text-align:left">'+escHtml(r.label)+'</td>'+
        '<td>'+(r.gpm==null?'—':Math.round(r.gpm))+'</td>'+
        '<td class="'+awtCls(r.avg_watch_sec)+'">'+(r.avg_watch_sec==null?'—':r.avg_watch_sec+'s')+'</td>'+
        '<td>'+pct(r.ctr)+'</td><td>'+pct(r.cto)+'</td>'+
        '<td>'+(r.orders_per_hour==null?'—':r.orders_per_hour)+'</td>'+
        '<td>'+fmt(r.peak_concurrent)+'</td><td class="pc">'+money(r.gmv)+'</td></tr>').join('')+
      '</table></div>';
    $('llView').innerHTML=h;
  }catch(e){$('llView').innerHTML='<div class="card"><div class="err">'+e.message+'</div></div>';}}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _auth_ok(self):
        if not DASH_PW:
            return True
        hdr = self.headers.get("Authorization", "")
        if hdr.startswith("Basic "):
            try:
                _, pw = base64.b64decode(hdr[6:]).decode().split(":", 1)
                if pw == DASH_PW:
                    return True
            except Exception:
                pass
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="QVC Dashboard"')
        self.send_header("Content-Length", "0")
        self.end_headers()
        return False

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._auth_ok():
            return
        body = PAGE.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self._auth_ok():
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/scan":
                data = scan(req.get("shop_id", DEFAULT_SHOP["shop_id"]),
                            int(req.get("window", 7)), int(req.get("top", 30)),
                            int(req.get("min_units", 50)),
                            bool(req.get("refresh")),
                            int(req.get("pages", 1)),
                            float(req["rev_min"]) if req.get("rev_min") not in (None, "") else None,
                            float(req["rev_max"]) if req.get("rev_max") not in (None, "") else None,
                            req.get("keyword") or None,
                            req.get("launched") or None,
                            req.get("sort") or "per_creator",
                            bool(req.get("confirmed")))
            elif self.path == "/api/shops":
                data = shop_search(req["keyword"])
            elif self.path == "/api/product":
                data = product_search(req["keyword"], int(req.get("window", 7)),
                                      req.get("shop_id") or None)
            elif self.path == "/api/detail":
                data = product_detail(str(req["product_id"]),
                                      int(req.get("window", 7)))
            elif self.path == "/api/cache":
                data = cached_products()
            elif self.path == "/api/livestreams":
                data = livestreams(req.get("shop_id", DEFAULT_SHOP["shop_id"]),
                                   int(req.get("window", 7)))
            elif self.path == "/api/save_shop":
                data = save_shop(str(req["shop_id"]), req.get("shop_name"))
            elif self.path == "/api/saved_shops":
                data = saved_shops()
            elif self.path == "/api/remove_shop":
                data = remove_shop(str(req["shop_id"]))
            elif self.path == "/api/live/list":
                data = live_list()
            elif self.path == "/api/live/save":
                data = live_save(req)
            elif self.path == "/api/live/get":
                data = live_get(req["id"])
            elif self.path == "/api/live/delete":
                data = live_delete(req["id"])
            elif self.path == "/api/live/checkin":
                data = live_checkin_add(req)
            elif self.path == "/api/live/trends":
                data = live_trends()
            elif self.path == "/api/live/import":
                data = live_import(req.get("csv") or "")
            elif self.path == "/api/live/import_file":
                raw = base64.b64decode(req.get("b64", "") or "")
                data = live_import_any(raw, req.get("filename", ""))
            elif self.path == "/api/live/update_downloads":
                data = live_update_from_downloads()
            else:
                return self._json({"error": "unknown endpoint"}, 404)
            self._json({"data": data, "credits_used": CREDITS["used"]})
        except Exception as e:
            self._json({"error": str(e), "credits_used": CREDITS["used"]})


class ThreadingHTTPServer(HTTPServer):
    daemon_threads = True

    def process_request(self, request, client_address):
        t = threading.Thread(target=self._handle, args=(request, client_address))
        t.daemon = True
        t.start()

    def _handle(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        finally:
            self.shutdown_request(request)


if __name__ == "__main__":
    seed_cache_if_needed()
    seed_live_if_needed()
    print(f"QVC Opportunity Dashboard running:")
    print(f"  This Mac:   http://localhost:{PORT}")
    print(f"  Phone/iPad: http://{os.uname().nodename}:{PORT}  (same wifi)")
    print("Press Ctrl+C to stop.")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
