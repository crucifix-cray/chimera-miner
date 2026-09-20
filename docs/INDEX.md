# CHIMERA INDEX — Roadmap & Fleet Status

**Updated:** 2026-09-20 ~19:05 UTC

## Where we are now
- **1 miner LIVE:** cell-16 / session-2 (`altonlehman16@gmail.com`) / project `7d6f77a6` / full mode / Chromium. Health checks passing, worker alive in Lovable sandbox.
- **Sessions:** 36 in GitHub DB, 34 active (s1 burned, 1 red).
- **Projects:** 3 in DB, but only `7d6f77a6` proven working. `cff0cbd4` dead, `9db2f406` unverified.
- **Other 50 cells:** online, idle, old code (Firefox script3 that dies in ~3 min).
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app` (alive, 426 = WS-only).
- **Key scripts:** `chimera-miner/stable_browser.py` (reusable launcher), `script3_launch_miner.py` (`--browser chromium --project <id>`), `src/lovable/load_session_with_rescue.py` (full-state rescue).

## Docs map
| Doc | What |
|---|---|
| `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md` | 5 problems + fixes (dead project, Tor "snag", Firefox death, 1h cookie expiry, s4 password) |
| `docs/PIPELINE.md` | Canonical pipeline: rescue → script2 → script3 |
| `docs/LOVABLE.md` | 36 Lovable accounts, creds, TOTP |
| `docs/HANDOFF-BLAST.md` | 50×10 blast state |
| `docs/HANDOFF_SCRIPT3_DIAGNOSIS_2026-09-20.md` | cell-25/session-4 failure diagnosis |
| `railway-miner/HANDOFF_PROMPT.md` | Sep-14 miner service history (deleted) |

## Roadmap to all-Lovables mining

### Phase 1 — Prove & lock single-miner stability (NOW)
- [ ] cell-16 miner survives 24h (watch health checks, bridge shares accepted)
- [ ] Confirm bridge `0703` receives hashes from `moly` worker
- [ ] Record expiry behavior: does full-state + Firebase refresh keep session alive past 1h without re-login?

### Phase 2 — Project factory (script2 per session)
Each of the 34 active sessions needs ≥1 **verified working** project (chat input loads, no "snag", no "no access").
- [ ] Run script2 `--mode template` (prompt: `Build a debug terminal.txt`) for sessions missing projects
- [ ] Verify each new project with `stable_browser.py --url <project> --shot` (chat_inputs=1) before assigning miners
- [ ] Register verified projects in GitHub DB (`data/database.json`) with `created_by` + usage counts
- [ ] Target: 34 sessions × 1 project minimum (later ×9 remixes each per farm plan)

### Phase 3 — Fleet rollout (51 cells)
For each cell:
- [ ] Push latest `script3_launch_miner.py` + `github_db.py` + `stable_browser.py` + session state trio (`cookies.json`, `localstorage.json`, `indexeddb.json`)
- [ ] Launch: `CHIMERA_NO_PROXY=1 ... --session session-N --mode full --threads 64 --project <id> --browser chromium`
- [ ] Verify: chat found → prompt sent → preview open → worker VERIFIED → health check OK
- [ ] Track per-cell: session, project, PID, log path, bridge worker name

### Phase 4 — Operations
- [ ] Bridge capacity: 34–51 concurrent workers vs `0703` limits — monitor, scale bridges if needed
- [ ] Session rotation: when a session dies (truly_red), script2 creates replacement project, script3 re-targets
- [ ] Cookie hygiene: nightly `load_session_with_rescue.py` pass over all sessions (saves fresh trio, refreshes Firebase tokens)
- [ ] Kill Tor usage everywhere for Lovable traffic (flagged IPs). Reserve WARP/Tor for account creation only.
- [ ] Deprecate Firefox path: default `--browser chromium` everywhere; keep InvisiblePlaywright only where stealth proven necessary

## TODO list (ordered)
1. [ ] Monitor cell-16 miner to 24h, confirm bridge shares
2. [ ] Verify `9db2f406` (session-4) loads or replace it via script2
3. [ ] Script2 run for all sessions without a verified project
4. [ ] Verify each project via `stable_browser.py` probe before assigning
5. [ ] Roll out script3+chromium to cells 1-by-1 (or in batches), one session per cell
6. [ ] Set up nightly cookie-refresh pass over all 34 sessions
7. [ ] Bridge load test at 10 → 34 concurrent workers
8. [ ] Document per-cell runbook (PID, log, restart command) in `docs/FLEET.md`
