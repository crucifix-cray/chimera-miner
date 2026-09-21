# CHIMERA INDEX — Roadmap & Fleet Status

**Updated:** 2026-09-21 ~06:00 UTC

## Where we are now
- **1 miner LIVE:** cell-16 / session-2 (`altonlehman16@gmail.com`) / project `7d6f77a6` / **autonomous daemon** / Chromium. Health checks passing every 3 min, worker alive in Lovable sandbox. Token refresh every 40 min.
- **Daemon:** `chimera-miner/daemon.py` — self-healing, runs forever. Sends build prompt → waits for sandbox → injects worker → health loop + token refresh + auto-recovery. No manual intervention needed.
- **Sessions:** 36 in GitHub DB, 34 active (s1 burned, 1 red).
- **Projects:** 3 in DB, but only `7d6f77a6` proven working. `cff0cbd4` dead, `9db2f406` unverified.
- **Other 50 cells:** online, idle, old code.
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app` (alive, 426 = WS-only).
- **Key scripts:** `daemon.py` (autonomous miner), `script3_launch_miner.py` (manual launcher), `stable_browser.py` (reusable launcher), `src/lovable/load_session_with_rescue.py` (full-state rescue).

## Architecture

```
daemon.py (runs forever)
├── Setup: Launch Chromium → load cookies → restore localStorage + IndexedDB
├── Login check: if /login → do_login (email + password + TOTP)
├── Chat: open chat page → send build prompt ("say 'x'")
├── Preview: open preview → wait for sandbox (doc bridge, max 60s)
├── Inject: inject_miner() → worker starts in sandbox
├── Health loop (every 3 min):
│   ├── Probe worker: window.doc("ps -A | grep sysoptd")
│   ├── If dead → reload preview → wait for sandbox → re-inject
│   └── Mouse wiggle (human presence)
├── Token refresh (every 40 min):
│   ├── POST refreshToken to securetoken.googleapis.com
│   └── Save updated cookies + localStorage + IndexedDB
└── On crash: relaunch browser, reload state, restart everything
```

## Docs map
| Doc | What |
|---|---|
| `docs/INDEX.md` | This file — roadmap, fleet status, TODO |
| `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md` | 9 problems + fixes documented |
| `docs/HANDOFF.md` | Handoff prompt for continuing agent |
| `docs/PIPELINE.md` | Canonical pipeline: rescue → script2 → daemon |
| `docs/LOVABLE.md` | 36 Lovable accounts, creds, TOTP |

## Roadmap to all-Lovables mining

### Phase 1 — Prove & lock single-miner stability ✅ DONE
- [x] cell-16 miner running autonomously via daemon.py
- [x] Health checks passing (3 consecutive checks verified)
- [x] Token refresh working (Firebase refresh token valid)
- [x] Sandbox crash recovery working (refresh + re-inject)

### Phase 2 — Project factory (script2 per session)
Each of the 34 active sessions needs ≥1 **verified working** project.
- [ ] Run script2 `--mode template` for sessions missing projects
- [ ] Verify each project with `stable_browser.py --shot` (chat_inputs=1)
- [ ] Register in GitHub DB (`data/database.json`)
- [ ] Target: 34 sessions × 1 project minimum

### Phase 3 — Fleet rollout (34 sessions)
For each session:
- [ ] Rescue session: `python3 load_session_with_rescue.py N --kernel`
- [ ] Create/verify project via script2
- [ ] Deploy daemon: `python3 daemon.py --session session-N --project <id> --browser chromium`
- [ ] Verify: health check passing, worker alive
- [ ] Track: session, project, PID, log path

### Phase 4 — Operations
- [ ] Bridge capacity: 34+ concurrent workers vs `0703` limits
- [ ] Session rotation: when session dies → script2 creates replacement project → daemon re-targets
- [ ] Cookie hygiene: daemon auto-refreshes every 40 min (no manual pass needed)
- [ ] Deprecate Firefox: default `--browser chromium` everywhere

## TODO list (ordered)
1. [ ] Monitor cell-16 daemon for 24h stability
2. [ ] Rescue remaining 33 sessions via OnKernel browsers
3. [ ] Script2 run for all sessions without a verified project
4. [ ] Verify each project before assigning
5. [ ] Deploy daemon to each cell (one session per cell)
6. [ ] Bridge load test at 10 → 34 concurrent workers
