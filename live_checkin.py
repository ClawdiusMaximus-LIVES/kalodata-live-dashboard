#!/usr/bin/env python3
"""Log a mid-stream check-in and print the STAY / SWAP / END call.

Built for the case where the LIVE Board export is NOT downloadable mid-stream:
Mike screenshots the LIVE Board, Claude reads the numbers off the screenshot and
runs this. No typing by Mike, no export needed.

  python3 live_checkin.py --minute 45 --concurrent 38 --entries 210 \
      --comments 12 --clicks 24 --orders 1 --gmv 39.99

  python3 live_checkin.py --new "Jackery push"     # start today's stream row
  python3 live_checkin.py --status                 # current badge, no write
"""
import argparse, datetime as dt, json, sys, urllib.request

BASE = "http://localhost:8787"


def call(path, payload):
    req = urllib.request.Request(BASE + path, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    r = json.load(urllib.request.urlopen(req, timeout=30))
    if r.get("error"):
        print("ERROR:", r["error"]); sys.exit(1)
    return r.get("data")


def current_stream():
    """Newest stream for today, else the newest overall."""
    rows = call("/api/live/list", {})
    if not rows:
        return None
    today = dt.date.today().isoformat()
    todays = [r for r in rows if r.get("date") == today]
    return (todays or rows)[0]


def show(sid):
    d = call("/api/live/get", {"id": sid})
    s, dec = d["stream"], d["decision"]
    print(f"\n  Stream #{sid}  {s.get('title') or s.get('date')}")
    print(f"  {len(d.get('checkins', []))} check-ins | ${s.get('gmv') or 0:,.2f} "
          f"| {s.get('orders') or 0} orders")
    print(f"\n  >>> {dec['status']}   ({dec['phase']}, minute {dec['minute']})")
    for r in dec["reasons"]:
        print(f"      - {r}")
    print()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--new", metavar="TITLE", help="create today's stream row")
    p.add_argument("--status", action="store_true", help="show badge, write nothing")
    p.add_argument("--stream", type=int, help="stream id (default: today's newest)")
    p.add_argument("--minute", type=int)
    p.add_argument("--concurrent", type=int)
    p.add_argument("--entries", type=int)
    p.add_argument("--comments", type=int)
    p.add_argument("--clicks", type=int)
    p.add_argument("--orders", type=int)
    p.add_argument("--gmv", type=float)
    p.add_argument("--note")
    a = p.parse_args()

    if a.new:
        now = dt.datetime.now()
        sid = call("/api/live/save", {"title": a.new, "date": now.date().isoformat(),
                                      "start_time": now.strftime("%H:%M")})["id"]
        print(f"Started stream #{sid}: {a.new} at {now.strftime('%H:%M')}")
        return

    st = call("/api/live/get", {"id": a.stream})["stream"] if a.stream else current_stream()
    if not st:
        print("No stream yet. Run:  python3 live_checkin.py --new \"Title\"")
        sys.exit(1)
    sid = st["id"]

    if a.status:
        show(sid); return

    if a.minute is None:
        print("Need --minute (minutes since the live started)."); sys.exit(1)
    call("/api/live/checkin", {
        "stream_id": sid, "minute": a.minute, "entries": a.entries,
        "concurrent": a.concurrent, "comments": a.comments,
        "product_clicks": a.clicks, "orders": a.orders, "gmv": a.gmv,
        "note": a.note})
    print(f"Logged minute {a.minute}.")
    show(sid)


if __name__ == "__main__":
    main()
