#!/bin/bash
set -e

echo "=== Railway Miner Container Started ==="
echo "Date: $(date)"
echo "Hostname: $(hostname)"
echo "Memory: $(free -h | grep Mem | awk '{print $2}')"

# Start Xvfb in background
echo "Starting Xvfb..."
Xvfb :99 -screen 0 800x600x16 &
export DISPLAY=:99
sleep 2

# Wait for manual command
echo ""
echo "=== Container ready! ==="
echo ""
echo "To run the miner, SSH into Railway and run:"
echo ""
echo "  cd /app"
echo "  python3 script3_launch_miner.py --session 4 --mode full"
echo ""
echo "Or for oneshot test:"
echo ""
echo "  python3 script3_launch_miner.py --session 4 --mode oneshot"
echo ""
echo "Container will stay alive. Logs will appear here."
echo ""

# Keep container alive
tail -f /dev/null
