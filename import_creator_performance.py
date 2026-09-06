#!/usr/bin/env python3
"""Import a TikTok "Creator Live Performance" export (one row PER STREAM, the
Analytics > LIVE Analytics > All LIVE videos export) into the dashboard live log.

This is the multi-stream summary format (Room ID, Room Title, Start Time, GMV,
Views, GPM, CTR, ...). Complements import_live_board.py (single-stream 5-min
intervals). Accepts .xlsx or .csv.

Usage: python3 import_creator_performance.py CreatorLivePerformance_*.xlsx
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dashboard as D
from import_live_board import load_xlsx, load_csv, num


def pct(v):
    """'1.610986%' -> 0.01611 (fraction)."""
    if v in (None, ""):
        return None
    return round(num(v) / 100.0, 6)


def text(v):
    return str(v).strip() if v not in (None, "") else None


def theme(title):
    """Normalize a room title to a product theme so trends can group by product.
    e.g. 'Convert a Bench Last Chance!' -> 'Convert a Bench'."""
    t = (title or "").strip()
    tl = t.lower()
    known = ["convert a bench", "nugget ice", "back to school", "jabberin jack",
             "jabberin' jack", "skil", "power hour", "luxury pillow", "caraway",
             "megachef", "halloween", "meshy mat", "vitamix", "cuisinart",
             "blackstone", "bella", "beast"]
    for k in known:
        if k in tl:
            return k.title().replace("Skil", "SKIL")
    # fallback: first 3 words, stripped of hype punctuation
    words = re.sub(r"[^A-Za-z0-9 ]", "", t).split()
    return " ".join(words[:3]) if words else "Untitled"


# export column name -> our live_stream field (None = handled specially / skipped)
COLMAP = {
    "Room Title": ("title", text),
    "Duration": None,            # -> duration_min (parsed)
    "Start Time": None,          # -> date + start_time (parsed)
    "Attributed GMV": ("gmv", num),
    "Attributed orders": ("orders", num),
    "AOV": ("aov", num),
    "Views": ("unique_viewers", num),
    "Impressions": ("impressions", num),
    "Watch GPM": ("gpm", num),
    "Avg. viewing duration": ("avg_watch_sec", num),
    "Tap through rate": ("join_rate", pct),
    "Product clicks": ("product_clicks", num),
    "CTR": ("ctr", pct),
    "CTOR": ("cto", pct),
    "New followers": ("new_followers", num),
    "Comments": ("comments", num),
    "Shares": ("shares", num),
    "Likes": ("likes", num),
}


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 import_creator_performance.py FILE.xlsx|FILE.csv")
    path = sys.argv[1]
    sheets = load_xlsx(path) if path.lower().endswith(".xlsx") else load_csv(path)
    rows = sheets.get("performance_detail") or next(iter(sheets.values()))

    hi = next((i for i, r in enumerate(rows)
               if r and any(str(c).strip() == "Room ID" for c in r if c)), None)
    if hi is None:
        sys.exit("Could not find the 'Room ID' header row — is this a Creator "
                 "Live Performance export?")
    hdr = [str(c).strip() if c is not None else "" for c in rows[hi]]

    def gi(name):
        return hdr.index(name) if name in hdr else None

    imported, skipped, results = 0, 0, []
    for r in rows[hi + 1:]:
        if not r or not any(str(c).strip() for c in r if c is not None):
            continue
        st_i = gi("Start Time")
        st = str(r[st_i]) if (st_i is not None and st_i < len(r) and r[st_i]) else ""
        m = re.search(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", st)
        if not m:
            skipped += 1
            continue
        date, start_time = m.group(1), m.group(2)
        stream = {"date": date, "start_time": start_time}
        du_i = gi("Duration")
        if du_i is not None and du_i < len(r) and r[du_i]:
            dm = re.match(r"(?:(\d+)h)?(?:(\d+)m)?", str(r[du_i]))
            if dm:
                stream["duration_min"] = int(dm.group(1) or 0) * 60 + int(dm.group(2) or 0)
        for name, spec in COLMAP.items():
            if not spec:
                continue
            i = gi(name)
            if i is None or i >= len(r):
                continue
            field, fn = spec
            stream[field] = fn(r[i])
        rid_i = gi("Room ID")
        if rid_i is not None and rid_i < len(r) and r[rid_i]:
            stream["room_id"] = str(r[rid_i])
        stream["products"] = theme(stream.get("title"))
        # de-dupe on room_id (falls back to date+start_time if no room_id)
        ex = D.live_find_by_room(stream.get("room_id"))
        if not ex:
            con = D.db()
            row = con.execute("SELECT id FROM live_stream WHERE date=? AND "
                              "IFNULL(start_time,'')=IFNULL(?,'')",
                              (date, start_time)).fetchone()
            con.close()
            ex = row[0] if row else None
        if ex:
            D.live_delete(ex)
        sid = D.live_save(stream)["id"]
        imported += 1
        results.append((date, start_time, stream.get("title", ""),
                        stream.get("gmv") or 0, stream.get("orders") or 0))

    results.sort(key=lambda x: -x[3])
    print(f"Imported {imported} streams ({skipped} rows skipped, no timestamp).")
    total_gmv = sum(x[3] for x in results)
    total_orders = sum(x[4] for x in results)
    print(f"Totals across import: ${total_gmv:,.2f} GMV, {total_orders} orders.\n")
    print("Top streams by GMV:")
    for date, t, title, gmv, orders in results[:8]:
        print(f"  ${gmv:>8,.2f} | {orders:>2} ord | {date} {t} | {title}")
    print("\nOpen the dashboard -> LIVE Log tab -> Trends to see GMV by product / "
          "hour / weekday across all of them.")


if __name__ == "__main__":
    main()
