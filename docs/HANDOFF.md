# HANDOFF — Continue Chimera Fleet Deployment

**Updated:** 2026-09-21 ~22:15 UTC

You are continuing autonomous miner fleet deployment. One miner is live and self-healing on cell-16. Your job: scale to all 34 sessions.

**Read first:** `docs/DAEMON-RAILWAY.md` (exact Railway service IDs, launch cmd, sync rules).

## What's Already Done
- `daemon.py` is the production miner — full-mode health + **fail-fast** revive (wake → lovable → inject)
- Session-2 (`altonlehman16@gmail.com`) on **cell-16**, project `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`
- Live cell `daemon.py` + `miner_injector.py` md5-match repo `master` after each deploy
- GitHub DB backend (`github_db.py`) — Mega retired for this fleet path
- Bridge: `wss://chimera-bridge-production-0703.up.railway.app` (**not** 0ef2)
- Documented problems + fixes: `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md` (incl. 11–17 revive/fail-fast)

## Critical Rules (NEVER VIOLATE)
- `CHIMERA_NO_PROXY=1` always — proxied IPs get Lovable error pages
- `--browser chromium` on containers — Firefox dies after ~3min
- `--mode full` on Railway (oneshot exits after inject)
- Never commit secrets/cookies/tokens
- Skip session-1 (burned)
- One browser per cell; never `pkill -f` matching own SSH cmdline — kill by exact PID/`/opt/venv/bin/python3 -u daemon.py` only
- **save_trio always from chat page** (lovable.dev) — never from preview
- Wake prompts only (`say 'a'`, `2+2?`, …) — NOT script2 “Build a debug terminal”
- **Fail-fast revive:** wall 180s, 2 fails → browser restart; no `?_wake=`; no reload-on-empty body
- After every `daemon.py` push: `curl` raw GitHub onto cell + restart daemon; verify md5

## Credentials
- **OnKernel API:** `sk_65153b1d-9bc1-081c-f09f-9c97f1ddb02b.RR1CxEZUyjkV4yKV53f59W8gLKX4O90HfWTFZciIwyA`
- **ZenRows (fallback):** `7213c8436771ba990ec226f68d64b3d6c1e666f3`
- **GH PAT:** See `automation-toolkit/docs/CREDENTIALS.md` (never commit token values)
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app`
- **Railway SSH:** cellkey under `automation-toolkit/sessions/session-2/.ssh/cellkey`; project/env/service IDs in `docs/DAEMON-RAILWAY.md`

## Sessions Needing Rescue (33 remaining)
Sessions: 4, 6, 7, 8, 9, 11, 16, 20, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51

```bash
cd /home/alae/Documents/repos/automation-toolkit
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
