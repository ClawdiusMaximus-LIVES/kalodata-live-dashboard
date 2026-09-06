# Kalodata / TikTok LIVE Dashboard

Mike's TikTok LIVE performance dashboard + QVC opportunity scanner. Stdlib Python,
one process (UI + API + SQLite). Read `MACBOOK_HANDOFF.md` first if you're a Claude
Code instance, and `CLAUDE.md` for full project context.

## Run it (on the Mac you stream from)
```
python3 dashboard.py
```
Then open http://localhost:8787 → the 🔴 LIVE Log tab. Or double-click `start.command`.

The **⚡ Update from latest download** button reads THIS machine's `~/Downloads`,
grabs the newest TikTok LIVE Board export, and loads the whole curve + STAY/SWAP/END
badge — no typing. (That only works when the dashboard runs on the same Mac you
downloaded on. A cloud/Railway copy can't read your local Downloads.)

## Data
`cache.db` holds 37 imported streams (Aug–Sep 2026) + the QVC product cache.
No API key is in this repo — the LIVE Log needs none. (The QVC scanner tabs need
`KALODATA_API_KEY`; set it in the env only if you use those.)
