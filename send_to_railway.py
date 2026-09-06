#!/usr/bin/env python3
"""Push LIVE Board exports from ~/Downloads up to the Railway dashboard.

Railway is the permanent record after a live is over; it cannot reach this Mac's
Downloads folder itself, so this sends the files to it. Safe to run twice --
imports dedupe by TikTok Room ID.

Usage:  python3 send_to_railway.py [--days N]     (default: files from last 2 days)
"""
import base64, json, os, sys, time
import urllib.request, urllib.error

URL = os.environ.get("KALO_RAILWAY_URL",
                     "https://kalodata-production.up.railway.app")
DAYS = 2
if "--days" in sys.argv:
    DAYS = int(sys.argv[sys.argv.index("--days") + 1])
if "--all" in sys.argv:
    DAYS = 3650


def exports(days):
    dl = os.path.expanduser("~/Downloads")
    if not os.path.isdir(dl):
        return []
    cutoff = time.time() - days * 86400
    out = []
    for f in os.listdir(dl):
        low = f.lower()
        if not (low.endswith(".xlsx") or low.endswith(".csv")):
            continue
        if not any(k in low for k in ("live", "dashboard", "creator", "performance")):
            continue
        p = os.path.join(dl, f)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if mt >= cutoff:
            out.append((mt, p, f))
    return sorted(out)


def push(path, fname):
    with open(path, "rb") as fh:
        body = json.dumps({"filename": fname,
                           "b64": base64.b64encode(fh.read()).decode()}).encode()
    req = urllib.request.Request(URL.rstrip("/") + "/api/live/import_file",
                                 data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def main():
    files = exports(DAYS)
    print(f"\nSending to {URL}")
    if not files:
        print(f"\n  No LIVE exports in ~/Downloads from the last {DAYS} day(s).")
        print("  Download one from the TikTok LIVE Board first, then run this again.")
        print("  (To send older files: add  --all )")
        return 1
    print(f"Found {len(files)} export(s) from the last {DAYS} day(s).\n")
    ok = fail = 0
    for _mt, path, fname in files:
        sys.stdout.write(f"  {fname} ... ")
        sys.stdout.flush()
        try:
            res = push(path, fname)
            d = res.get("data") or {}
            if res.get("error") or d.get("error"):
                print(f"FAILED: {res.get('error') or d.get('error')}")
                fail += 1
            else:
                n = d.get("imported") or d.get("checkins") or ""
                print(f"OK  (${d.get('gmv', 0):,.2f}, {d.get('orders', 0)} orders"
                      + (f", {n} check-ins" if n else "") + ")")
                ok += 1
        except urllib.error.URLError as e:
            print(f"FAILED: {e}")
            fail += 1
    print(f"\nDone: {ok} sent, {fail} failed.")
    print(f"View it anywhere: {URL}\n")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
