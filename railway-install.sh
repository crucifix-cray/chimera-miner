#!/bin/bash
# Railway Miner Quick Install Script
# Run this inside Railway container shell

set -e

echo "=== Installing Chimera Miner on Railway ==="

# Update and install dependencies
apt-get update -qq
apt-get install -y python3 python3-pip firefox xvfb curl git rclone wget

# Install Playwright
pip3 install --break-system-packages playwright
playwright install firefox
playwright install-deps firefox

# Create app directory
mkdir -p /app
cd /app

# Download miner files from GitHub
echo "Downloading miner files..."
curl -sL https://raw.githubusercontent.com/crucifix-cray/chimera-miner/main/script3_launch_miner.py -o script3_launch_miner.py
curl -sL https://raw.githubusercontent.com/crucifix-cray/chimera-miner/main/miner_injector.py -o miner_injector.py
curl -sL https://raw.githubusercontent.com/crucifix-cray/chimera-miner/main/mega_db.py -o mega_db.py

# Create rclone config
mkdir -p /root/.config/rclone
cat > /root/.config/rclone/rclone.conf <<'EOF'
[mega]
type = mega
user = emilypeterson30@mail.findmeghana.org
pass = AIjpeMEdPQWNTQHR6YYDYjcEoGFSOGHASO5DjwkHcXUW7iDLFg
session_id = YHpE8zZFzThFIYjGGm44xFcyUGl1YWtCWlE4_HnRwxFodO1IlI4aFoyFUg
master_key = s6SFGB0f4UZk7VYPwK/k3A==
endpoint = https://eu.api.mega.co.nz/
EOF

# Create session-4 directory and config
mkdir -p /app/sessions/session-4
cat > /app/sessions/session-4/config.json <<'EOF'
{
  "email": "dakarihickmanhickman@gmail.com",
  "password": "dakarihickmanhickman@gmail.com1",
  "totp_secret": "SQ4RE3WBKH3AT33FU6W7LMDDWUDHWL5U",
  "totp_backup": "XACBVSQOIRFRRI6THICIARXGUMFRWKPU"
}
EOF

# Download cookies
echo "Downloading session cookies..."
curl -sL https://raw.githubusercontent.com/crucifix-cray/chimera-miner/main/railway-deploy/sessions/session-4/cookies.json -o /app/sessions/session-4/cookies.json

# Start Xvfb
echo "Starting Xvfb..."
Xvfb :99 -screen 0 800x600x16 > /dev/null 2>&1 &
export DISPLAY=:99
sleep 2

echo ""
echo "=== Installation Complete! ==="
echo ""
echo "Run the miner with:"
echo ""
echo "  cd /app"
echo "  export DISPLAY=:99"
echo "  python3 script3_launch_miner.py --session 4 --mode oneshot"
echo ""
echo "Or for continuous mining:"
echo ""
echo "  python3 script3_launch_miner.py --session 4 --mode full"
echo ""
