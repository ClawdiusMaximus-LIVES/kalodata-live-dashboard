#!/usr/bin/env python3
"""Import a TikTok LIVE Board single-stream export (the monitor-icon export,
5-minute intervals) into the dashboard's live log.

This is DIFFERENT from the one-row-per-stream "Creator Live Performance" CSV that
dashboard.py's /api/live/import handles. This one takes ONE stream's minute-by-
minute export (like LIVE_Dashboard_2.xlsx) and turns it into a single live_stream
row + a 15-minute-bucketed check-in timeline, so the decision badge and curve work.

Usage:  python3 import_live_board.py path/to/LIVE_Dashboard.xlsx
        python3 import_live_board.py path/to/export.csv       (also accepts CSV)

Reuses dashboard.py's tables/coercion (stdlib only — no openpyxl needed)."""
import csv as _csv
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dashboard as D  # reuses db(), live_save(), live_checkin_add()

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _col_idx(ref):
    letters = re.match(r"[A-Z]+", ref or "A").group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def load_xlsx(path):
    """Return {sheet_name: [row_lists]} using stdlib only."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.iter(NS + "si"):
            shared.append("".join(t.text or "" for t in si.iter(NS + "t")))
    rels = {}
    root = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    for rel in root.iter(PKG_REL + "Relationship"):
        rels[rel.get("Id")] = rel.get("Target")
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    sheets = {}
    for sh in wb.iter(NS + "sheet"):
        name = sh.get("name")
        rid = sh.get(RNS + "id")
        target = (rels.get(rid, "") or "").lstrip("/")
        names = z.namelist()
        if target not in names and ("xl/" + target) in names:
            target = "xl/" + target
        rows = []
        sroot = ET.fromstring(z.read(target))
        for row in sroot.iter(NS + "row"):
            cells = {}
            maxc = -1
            for c in row.iter(NS + "c"):
                idx = _col_idx(c.get("r", "A1"))
                v = c.find(NS + "v")
                val = v.text if v is not None else None
                if c.get("t") == "s" and val is not None:
                    val = shared[int(val)]
                cells[idx] = val
                maxc = max(maxc, idx)
            rows.append([cells.get(i) for i in range(maxc + 1)])
        sheets[name] = rows
    return sheets


def load_csv(path):
    with open(path, newline="") as f:
        return {"All": [r for r in _csv.reader(f)]}


def num(v):
    if v is None:
        return 0.0
    s = re.sub(r"[^0-9.\-]", "", str(v))
    try:
        return float(s) if s not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0


def find_header(rows):
    for i, r in enumerate(rows):
        if r and any(str(c).strip() == "Datetime" for c in r if c is not None):
            return i
    raise SystemExit("Could not find the 'Datetime' header row — is this a LIVE "
                     "Board single-stream export?")


def meta_value(rows, label):
    for r in rows:
        if r and r[0] == label and len(r) > 1:
            return r[1]
    return None


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: python3 import_live_board.py FILE.xlsx|FILE.csv")
    path = sys.argv[1]
    sheets = load_xlsx(path) if path.lower().endswith(".xlsx") else load_csv(path)
    allrows = sheets.get("All") or next(iter(sheets.values()))

    # --- stream-level meta ---
    started = meta_value(allrows, "Started") or ""
    m = re.search(r"(\d{1,2}:\d{2})(?::\d{2})?\s+(\d{4}-\d{2}-\d{2})", started)
    start_time, date = (m.group(1), m.group(2)) if m else (None, None)
    room_id = meta_value(allrows, "Room ID")
    room_id = str(room_id) if room_id else None
    dur = meta_value(allrows, "Duration") or ""
    dm = re.match(r"(?:(\d+)h)?(?:(\d+)m)?", dur)
    duration_min = (int(dm.group(1) or 0) * 60 + int(dm.group(2) or 0)) if dm else None

    hi = find_header(allrows)
    hdr = [str(c).strip() if c is not None else "" for c in allrows[hi]]
    data = [r for r in allrows[hi + 1:] if r and r[0]]

    def col(name):
        return hdr.index(name) if name in hdr else None

    def cell(r, name):
        i = col(name)
        return r[i] if (i is not None and i < len(r)) else None

    def total(name):
        return sum(num(cell(r, name)) for r in data)

    if not date and data:
        date = str(data[0][0])[:10]

    prod_imp = total("Product Impressions")
    clicks = total("Product Clicks")
    orders = int(total("Attributed orders"))
    gmv = total("Attributed GMV")
    concurrents = [num(cell(r, "Viewers")) for r in data]
    peak = int(max(concurrents)) if concurrents else None
    peak_i = concurrents.index(max(concurrents)) if concurrents else 0
    peak_min = (peak_i + 1) * 5

    # products from the Product sheet (top by impressions)
    products = ""
    psheet = sheets.get("Product")
    if psheet and len(psheet) > 1:
        prows = [r for r in psheet[1:] if r and len(r) > 4 and r[1]]
        prows.sort(key=lambda r: -num(r[4]))
        products = ", ".join(str(r[1]) for r in prows[:5])

    stream = {
        "room_id": room_id,
        "date": date, "start_time": start_time, "duration_min": duration_min,
        "title": "LIVE " + (date or ""), "products": products,
        "impressions": int(total("LIVE impression")),
        "unique_viewers": int(total("Views")),
        "peak_concurrent": peak,
        "avg_concurrent": int(round(sum(concurrents) / len(concurrents))) if concurrents else None,
        "comments": int(total("Comments")), "likes": int(total("Likes")),
        "shares": int(total("Shares")), "new_followers": int(total("New followers")),
        "product_clicks": int(clicks),
        "ctr": round(clicks / prod_imp, 6) if prod_imp else None,
        "cto": round(orders / clicks, 6) if clicks else 0.0,
        "orders": orders, "gmv": round(gmv, 2),
        "pcv_note": f"Peak {peak} concurrent at ~min {peak_min} — identify what you "
                    f"were doing/pitching then; that's the template.",
    }

    # Merge behavior: if this stream already exists (from the summary import,
    # matched by Room ID), keep its rich per-stream metrics and only add the
    # curve — replace check-ins + fill concurrent/pcv from the intervals.
    # Otherwise create the stream fresh from the interval aggregates.
    existing = D.live_find_by_room(room_id)
    if not existing:
        con = D.db()
        row = con.execute("SELECT id FROM live_stream WHERE date=? AND "
                          "IFNULL(start_time,'')=IFNULL(?,'')",
                          (stream["date"], stream["start_time"])).fetchone()
        con.close()
        existing = row[0] if row else None
    if existing:
        sid = existing
        D.live_clear_checkins(sid)
        D.live_save({"id": sid, "room_id": room_id,
                     "peak_concurrent": stream["peak_concurrent"],
                     "avg_concurrent": stream["avg_concurrent"],
                     "pcv_note": stream["pcv_note"]})
        merged = True
    else:
        sid = D.live_save(stream)["id"]
        merged = False

    # 15-min bucketed check-ins (3 x 5-min intervals per bucket)
    n = 0
    for b in range(0, len(data), 3):
        chunk = data[b:b + 3]
        if not chunk:
            continue
        minute = (b // 3 + 1) * 15
        last = chunk[-1]
        D.live_checkin_add({
            "stream_id": sid, "minute": minute,
            "entries": int(sum(num(cell(r, "Viewers entering")) for r in chunk)),
            "concurrent": int(num(cell(last, "Viewers"))),
            "comments": int(sum(num(cell(r, "Comments")) for r in chunk)),
            "product_clicks": int(sum(num(cell(r, "Product Clicks")) for r in chunk)),
            "orders": int(sum(num(cell(r, "Attributed orders")) for r in chunk)),
            "gmv": round(sum(num(cell(r, "Attributed GMV")) for r in chunk), 2),
        })
        n += 1

    dec = D.live_get(sid)["decision"]
    print(f"{'Merged curve into' if merged else 'Imported'} stream #{sid}: "
          f"{stream['date']} {stream['start_time']} ({duration_min} min)")
    print(f"  {stream['impressions']:,} impressions | {stream['unique_viewers']:,} views "
          f"| peak {peak} concurrent | {clicks:.0f} clicks | {orders} orders "
          f"| ${gmv:,.2f} GMV")
    print(f"  {n} check-ins (15-min buckets). Final decision badge: {dec['status']} "
          f"(phase {dec['phase']})")
    print("Open the dashboard -> LIVE Log tab to see the curve.")


if __name__ == "__main__":
    main()
