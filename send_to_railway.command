#!/bin/bash
# ============================================================
#  SEND YOUR LIVE DATA TO RAILWAY  --  double-click AFTER a live
#  Uploads the LIVE Board exports sitting in your Downloads to the
#  always-on Railway dashboard, so it stays the permanent record.
# ============================================================
cd "$(dirname "$0")"
python3 send_to_railway.py "$@"
echo ""
echo "Press return to close this window."
read _
