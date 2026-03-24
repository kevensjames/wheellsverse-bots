#!/bin/bash
# WheellsVerse — Launch Web Dashboard
# Opens at http://localhost:5050
cd "$(dirname "${BASH_SOURCE[0]}")"
source venv/bin/activate
echo ""
echo "  ✦ WheellsVerse Dashboard v2.0"
echo "  ✦ Opening → http://localhost:5050"
echo "  ✦ Press Ctrl+C to stop"
echo ""
python3 main.py --dashboard --port 5050
