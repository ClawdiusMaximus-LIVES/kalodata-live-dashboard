#!/bin/bash
# Double-click to start your TikTok LIVE dashboard on this Mac.
cd "$(dirname "$0")"
echo "Starting your TikTok LIVE dashboard..."
echo "Leave this window open while streaming. Close it to stop."
python3 dashboard.py &
SRV=$!
sleep 2
open "http://localhost:8787"
wait $SRV
