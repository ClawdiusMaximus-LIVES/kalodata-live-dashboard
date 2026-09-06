# Before every live — 3 steps

## 1. Start the dashboard
Open the folder `kalodata-live-dashboard` and **double-click `start.command`**.

A black window opens and says **DASHBOARD IS RUNNING**. Your browser opens by itself.
**Leave that black window open the whole live.** Closing it stops the dashboard.

## 2. Tick the auto-check box
In the browser, click the **🔴 LIVE Log** tab, then tick:

> **🔄 Auto-check every 5 min**

That's the only click you need. It starts OFF every time, so tick it every live.

## 3. During the live
Every ~15 min, reach over and hit the **download icon** on the TikTok LIVE Board.
That's it — a new file lands in Downloads and the dashboard pulls it in within
5 minutes, updates the curve, and updates the **STAY / SWAP / END** badge.

**Impatient?** Hit **⚡ Update from latest download** for an instant refresh.

### Watching from your phone or iPad
Same wifi, open: **http://192.168.68.61:8787**
(If that ever stops working, the black window prints the current address.)

---

## After the live — send it to Railway
Double-click **`send_to_railway.command`**.

It uploads the exports to https://kalodata-production.up.railway.app so the
always-on dashboard has the permanent record. Safe to run twice — it never
duplicates a stream.

Railway **cannot** read this Mac's Downloads folder on its own — that is a hard
security wall, not a setting. That is the whole reason the live dashboard runs
here and Railway is the after-the-fact record.

---

## If something goes wrong

**"Address already in use"** — `start.command` already handles this; it stops the
old one first. If it still complains, close the black window and double-click again.

**Nothing importing?** Check the file actually landed in Downloads. The dashboard
only picks up files with `live`, `dashboard`, `creator`, or `performance` in the name.
