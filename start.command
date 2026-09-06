#!/bin/bash
# ============================================================
#  START YOUR LIVE DASHBOARD  --  just double-click this file
#  Leave the window that opens alone. Close it when the live is over.
# ============================================================
cd "$(dirname "$0")"

# If a dashboard is already running from a previous live, stop it cleanly first.
OLD=$(lsof -ti :8787 2>/dev/null)
if [ -n "$OLD" ]; then
  echo "Stopping the old dashboard that was still running..."
  kill $OLD 2>/dev/null
  sleep 1
fi

echo ""
echo "  Starting your TikTok LIVE dashboard..."
echo ""

python3 dashboard.py &
SRV=$!

# Wait until it actually answers before opening the browser.
for i in $(seq 1 20); do
  if curl -s -o /dev/null "http://localhost:8787/"; then break; fi
  sleep 0.5
done

IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null)

echo ""
echo "  ============================================================"
echo "   DASHBOARD IS RUNNING"
echo ""
echo "   On this Mac:      http://localhost:8787"
if [ -n "$IP" ]; then
echo "   On phone/iPad:    http://$IP:8787   (same wifi)"
fi
echo ""
echo "   Go to the  LIVE Log  tab."
echo ""
echo "   FIRST: tick the  [x] Auto-check every 5 min  box."
echo ""
echo "   Then during the live just hit 'download data' on the"
echo "   TikTok LIVE Board every ~15 min. It imports itself."
echo "   Want it NOW? Hit  Update from latest download."
echo ""
echo "   LEAVE THIS WINDOW OPEN. Close it to stop."
echo "  ============================================================"
echo ""

open "http://localhost:8787"
wait $SRV
