# HANDOFF — Continue Chimera Fleet Deployment

**Updated:** 2026-09-22 ~00:20 UTC

You are continuing autonomous miner fleet deployment. One miner is live and self-healing on cell-16. Your job: scale to all 34 sessions.

**Read first:** `docs/DAEMON-RAILWAY.md` (exact Railway service IDs, launch cmd, sync rules).

## What's Already Done
- `daemon.py` production miner — **simple revive** + **never-exit** browser cycles
- Session-2 on **cell-16**, project `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`
- Live cell md5 = `13d5b7cb4b8b6961f2acd561aba2ad67` (`5492fdf`)
- Bridge: `wss://chimera-bridge-production-0703.up.railway.app` (**not** 0ef2)
- Problems doc: `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md` (through 19)

## Critical Rules (NEVER VIOLATE)
- `CHIMERA_NO_PROXY=1` always
- `--browser chromium` + `--mode full` on Railway
- Never commit secrets/cookies/tokens; skip session-1
- Kill daemon by exact PID only — never `pkill -f` (matches SSH cmdline)
- **save_trio from chat page only**
- Wake = trivial prompts only (not script2 debug-terminal)
- Revive = refresh chat → wake → wait → preview → inject
- Crash / script error → Browser cycle relaunch (never exit full mode)
- After every push: curl raw GitHub `daemon.py` onto cell + restart; verify md5

## Credentials
- **OnKernel API:** `sk_65153b1d-9bc1-081c-f09f-9c97f1ddb02b.RR1CxEZUyjkV4yKV53f59W8gLKX4O90HfWTFZciIwyA`
- **ZenRows (fallback):** `7213c8436771ba990ec226f68d64b3d6c1e666f3`
- **GH PAT:** See `automation-toolkit/docs/CREDENTIALS.md` (never commit token values)
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app`
- **Railway SSH:** cellkey under `automation-toolkit/sessions/session-2/.ssh/cellkey`; project/env/service IDs in `docs/DAEMON-RAILWAY.md`

## Sessions Needing Rescue (33 remaining)
Sessions: 4, 6, 7, 8, 9, 11, 16, 20, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51

```bash
cd /home/alan/Documents/repos/automation-toolkit
CHIMERA_NO_PROXY=1 python3 -u src/lovable/load_session_with_rescue.py N --kernel
```

## Per-Session Deployment Steps
1. Rescue session (above)
2. Verify/create project — `stable_browser.py --shot` or script2 `--mode template`
3. Push `daemon.py` (+ `miner_injector.py` if changed) to cell — prefer base64 over SSH, or curl raw `master` after git push
4. Launch with `--mode full` (see `docs/DAEMON-RAILWAY.md`)
5. Verify log: `Worker alive (probe: N)` + `Preview healthy`

```bash
cd /app/work/chimera-miner
# after deploying daemon.py from master
CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions \
/opt/venv/bin/python3 -u daemon.py --session session-N --project <project-id> \
  --browser chromium --mode full \
  > /app/work/daemon_sN.log 2>&1 &
```

## Key Files
| File | Purpose |
|---|---|
| `daemon.py` | **Production** autonomous miner (Railway) |
| `miner_injector.py` | `inject_miner()` + worker cmd |
| `docs/DAEMON-RAILWAY.md` | Cell-16 IDs, launch, sync checklist |
| `script3_launch_miner.py` | Manual launcher (legacy) |
| `github_db.py` | GitHub DB backend |
| `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md` | Problems + fixes |
| `automation-toolkit/.../load_session_with_rescue.py` | Session rescue |

## Daemon Architecture (full mode)
```
daemon.py
├── Chromium → cookies → LS + IDB (IDB restore ≤15s timeout)
├── Chat wake prompt → preview wait_for_lovable_console (commit reloads)
├── inject_miner → save_trio(chat_page)
├── Health (~3 min): shell_worker_status
│     DEAD → revive (wake+login+lovable+inject); 3 fails → browser restart
└── Token refresh (40 min) — locked out during revive
```

## What Success Looks Like
- 34 cells, each running one daemon `--mode full`
- Health: Worker alive + Preview healthy
- Cell file md5 == `master` `daemon.py` / `miner_injector.py`
- Bridge receiving hashes from workers

## Current Blockers
1. Only 1 project proven (`7d6f77a6`) — need script2 for remaining sessions
2. 33 sessions not rescued
3. Prefer deploy via base64 SSH or curl-from-GitHub after push
