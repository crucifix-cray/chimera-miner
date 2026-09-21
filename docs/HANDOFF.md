# HANDOFF — Continue Chimera Fleet Deployment

You are continuing autonomous miner fleet deployment. One miner is live and self-healing on cell-16. Your job: scale to all 34 sessions.

## What's Already Done
- `daemon.py` works — self-healing miner that runs forever (health checks, token refresh, auto-recovery)
- Session-2 (`altonlehman16@gmail.com`) running on cell-16, project `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`
- GitHub DB backend (`github_db.py`) replaces Mega — `data/database.json` has 36 sessions, 3 projects
- Session rescue script works (`load_session_with_rescue.py --kernel`)
- All 10 documented problems have fixes (see `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md`)

## Critical Rules (NEVER VIOLATE)
- `CHIMERA_NO_PROXY=1` always — proxied IPs get Lovable error pages
- `--browser chromium` on containers — Firefox dies after ~3min
- Never commit secrets/cookies/tokens
- Skip session-1 (burned)
- One browser per cell, never `pkill -f` own shell

## Credentials
- **OnKernel API:** `sk_65153b1d-9bc1-081c-f09f-9c97f1ddb02b.RR1CxEZUyjkV4yKV53f59W8gLKX4O90HfWTFZciIwyA`
- **ZenRows (fallback):** `7213c8436771ba990ec226f68d64b3d6c1e666f3`
- **GH PAT:** See `automation-toolkit/docs/CREDENTIALS.md` (never commit token values)
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app`
- **Railway SSH:** `/home/alan/Documents/railways/scripts/cell_ssh.sh <railway-session> <project> <env> <service> -- <cmd>`

## Sessions Needing Rescue (33 remaining)
Sessions: 4, 6, 7, 8, 9, 11, 16, 20, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51

Rescue each:
```bash
cd /home/alan/Documents/repos/automation-toolkit
CHIMERA_NO_PROXY=1 python3 -u src/lovable/load_session_with_rescue.py N --kernel
```
This creates an OnKernel browser, loads old cookies, checks login, saves fresh trio (cookies + localStorage + IndexedDB). Commit + push after each batch.

## Per-Session Deployment Steps
1. **Rescue session** (above)
2. **Verify/create project** — use `stable_browser.py --shot` to check if session has a working project. If not, run script2 `--mode template` to create one.
3. **Deploy daemon** — push `daemon.py` + session state to cell, launch:
```bash
# Push files (curl from GitHub works, base64 through SSH doesn't)
cd /app/work/chimera-miner
curl -sL -H "Authorization: token $GH_PAT" \
  'https://raw.githubusercontent.com/crucifix-cray/chimera-miner/master/daemon.py' \
  -o daemon.py

# Launch
CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions \
python3 -u daemon.py --session session-N --project <project-id> --browser chromium \
  > /app/work/daemon_sN.log 2>&1 &
```
4. **Verify** — check log for: "Worker alive (probe: 2)" + "Preview healthy"

## Key Files
| File | Purpose |
|---|---|
| `daemon.py` | Autonomous miner (runs forever, self-healing) |
| `script3_launch_miner.py` | Manual launcher (legacy) |
| `miner_injector.py` | `inject_miner()` function |
| `github_db.py` | GitHub DB backend |
| `data/database.json` | Session + project registry |
| `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md` | 10 problems + fixes |
| `automation-toolkit/src/lovable/load_session_with_rescue.py` | Session rescue |

## Daemon Architecture
```
daemon.py
├── Launch Chromium → load cookies → restore localStorage + IndexedDB
├── Login check → do_login (email + password + TOTP) if needed
├── Chat page → send build prompt → wait for sandbox (doc bridge)
├── inject_miner() → worker starts
├── Health loop (3 min): probe worker → if dead, reload + re-inject
├── Token refresh (40 min): POST refreshToken → save updated trio
└── On crash: relaunch browser, restart everything
```

## What Success Looks Like
- 34 cells, each running one daemon
- Each daemon: health checks passing, worker alive, token refreshed
- Bridge receiving hashes from all 34 workers
- Zero manual intervention required

## Current Blockers
1. **Only 1 project proven** (`7d6f77a6`) — need script2 for remaining sessions
2. **33 sessions not rescued** — run rescue script in parallel via OnKernel
3. **File transfer to cells** — `curl` from GitHub raw URL works; base64/hex through SSH doesn't
