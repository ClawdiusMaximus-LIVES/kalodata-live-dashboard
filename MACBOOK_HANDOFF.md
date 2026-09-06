# MacBook Handoff — Mike's TikTok LIVE Dashboard

_Read this first, then `CLAUDE.md`. You are a Claude Code instance running ON Mike's
MacBook. A sibling instance built all of this on his Mac Studio; this repo is the
handoff. Nothing from that conversation is lost — it's in these files._

## Who / why (read this, it matters)
Mike (@Mike & Mishka), TikTok Shop **affiliate creator**, streams TikTok Shop LIVE
from **this MacBook**. He is in an acute cash crunch — this is about making rent.
He did **$200–300k GMV/month and $86k commission** at his peak and has since
collapsed to ~$5k/month. This is a **recovery of a lost formula, not a cold start.**
He is **not a coder** — explain in plain terms, give copy-paste commands, automate
everything, verify before claiming success, one recommendation not twelve. He's
stressed and moves fast (voice-to-text — parse intent). Own your mistakes plainly;
never frame them as his.

## THE reason you exist on the MacBook
The dashboard's **⚡ Update from latest download** button reads the `~/Downloads`
of the machine running the app. Mike streams from this MacBook and downloads the
TikTok **LIVE Board export** here (`/Users/michaelmatthews/Downloads`). A cloud
(Railway) copy can NEVER read his local Downloads — hard browser/OS security wall.
So the dashboard must run **locally on this MacBook** for the one-click Update to
work. That's your job: get it running here.

## Your first tasks
1. This repo should be cloned at `~/kalodata` (if not, move/clone it there — the app
   keeps `cache.db` next to `dashboard.py`, so any folder works, but `~/kalodata`
   is the convention).
2. Run it: `python3 dashboard.py` (stdlib only; needs Python 3. If macOS prompts to
   install Command Line Tools, have Mike click Install, then rerun). Or double-click
   `start.command`.
3. Open http://localhost:8787 → **🔴 LIVE Log** tab. Confirm 37 streams load.
4. **Verify the money feature:** the **⚡ Update from latest download** button calls
   `/api/live/update_downloads`, which scans `~/Downloads` on THIS machine for the
   newest LIVE export and imports it (full curve + STAY/SWAP/END badge, no typing).
   Have Mike download a LIVE Board export, hit ⚡ Update, confirm it loads.
5. Keep it running while he streams (leave the terminal/`start.command` window open).

## How the dashboard works (already built — don't rebuild)
- `dashboard.py` — stdlib web app, port 8787. Tabs: Shop Scanner, Product Lookup,
  Livestreams (Kalodata scanner — needs API key), and **🔴 LIVE Log** (his own
  stream data, needs NO Kalodata credits).
- LIVE Log = `live_stream` + `live_checkin` SQLite tables. Endpoints:
  `/api/live/{list,save,get,delete,checkin,trends,import,import_file,update_downloads}`.
- **Import paths (no manual typing):**
  - `⚡ Update from latest download` → newest export in `~/Downloads` (local only).
  - `📥 Pick a file` → upload any export (works from any machine, incl. Railway).
  - Both handle BOTH export types: single-stream LIVE Board (5-min intervals →
    curve + check-ins) and the multi-stream "Creator Live Performance" summary.
    Dedup is by TikTok Room ID, so re-importing updates, never duplicates.
- **Decision badge** (from the check-in timeline): STAY / SWAP-CHANGE-FORMAT /
  END-ON-A-HIGH / END-NOT-CONVERTING (fires when past 45 min with 0 orders after a
  swap). Phase label: Active push (0–15) / Learning (15–60) / Adapting (60+).
- CLI importers (backup): `import_live_board.py FILE.xlsx` (single stream),
  `import_creator_performance.py FILE.xlsx` (summary).
- Also deployed on Railway (`kalodata-production.up.railway.app`) for view-from-
  anywhere; the local MacBook copy is what he uses live. Deploy with
  `railway up --detach --service kalodata` from the Studio (not usually needed here).

## What his DATA already says (from 37 streams — use this, it beats generic advice)
- **Saturday is his money day by far** ($3,857); then Sun/Fri; mid-week ≈ $0.
- **Mornings + 3pm win** (7am, 10am, 3pm, 9am, 6am). **Evenings are weak — ignore
  the generic "7–10pm" advice; his audience buys mornings/weekends.**
- **Winners:** Convert A Bench (high AOV), Back To School (impulse volume), Nugget
  Ice, **Jabberin' Jack / Halloween seasonal** ($584 in one stream). **SKIL tools
  are dead** ($6/stream — his data overruled the "sell tools to men" guess; trust
  his numbers over category instinct).
- **The core problem: average watch time is 10–20s (benchmark 90+).** The **June
  2026 algorithm update** started weighting retention/watch-time/monetization hard,
  which punished his low AWT → the collapse. His old brute-force (8-hour daily
  streams) worked pre-update but now dead air actively hurts. **Fix = win the first
  90 seconds + reset the room every 10 min. Grind = many short sessions at proven
  windows, not one marathon.**
- Product↔audience fit is now a distribution signal. His delivered room is 63% male,
  96% age 35+, 90% non-followers. Match product to that room (or run female-skewed
  products on his women-skewed account).

## Deliverables already produced (in this repo)
`LIVE_PLAYBOOK.md/.pdf` (how the algo works + benchmarks), `LIVE_TURNAROUND_PLAN`
(diagnosis + fix), `LIVE_GAME_PLAN` (his Saturday session schedule + what to run),
`LIVE_LOG_SPEC.md`, plus pre-stream checklist + 15-min check-in card PDFs.

## Open threads
- Jackery: #1 live product now, he has a power-station crowd, but his flash sale got
  pulled until Monday — save the hard Jackery push for when the deal returns; demo
  it meanwhile.
- Jabberin' Jack unit arrived broken; he may fix it or run Nugget Ice / Convert A
  Bench instead.
- Optional enhancement: have the local ⚡ Update also push imported streams up to
  Railway so the cloud view stays current (single source of truth).
