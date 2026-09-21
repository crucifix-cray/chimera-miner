# CHIMERA INDEX — Roadmap & Fleet Status

**Updated:** 2026-09-21 ~22:15 UTC

## Where we are now
- **1 miner LIVE:** cell-16 / session-2 (`altonlehman16@gmail.com`) / project `7d6f77a6` / **`daemon.py --mode full`** / Chromium. Health every ~3 min; **fail-fast** revive (≤~6 min 0-worker).
- **Canonical Railway runbook:** `docs/DAEMON-RAILWAY.md` (service IDs, launch cmd, file sync).
- **Repo = cell:** after push, deploy `daemon.py` (+ `miner_injector.py` if changed) so md5 matches `master`.
- **Sessions:** 36 in GitHub DB, 34 active (s1 burned).
- **Projects:** only `7d6f77a6` proven for session-2. Others in fleet are other accounts.
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app` (never 0ef2).
- **Key scripts:** `daemon.py` (production), `miner_injector.py`, `script3_launch_miner.py` (legacy), `stable_browser.py`, `load_session_with_rescue.py`.

## Architecture (current daemon)

```
daemon.py --mode full
├── Setup: Chromium → cookies → LS + IDB (timeouts on IDB)
├── Wake: trivial chat prompt (NOT script2 debug-terminal)
├── Preview: wait_for_lovable_console (auth-bridge wait; commit reload)
├── inject_miner() → save_trio from chat origin
├── Health (~180s / ~30s on fail):
│   ├── shell_worker_status 30s timeout (proxy-404 / nodoc / probe=0 → dead)
│   ├── revive ≤180s: clean goto chat → lovable (120s) → inject
│   │   abort wake on 2× dead eval/goto; NO ?_wake=; NO reload-on-empty
│   └── 2 revive fails → browser restart in 5s
└── Token refresh 40m (page_lock; 20s hard timeout)
```

## Docs map
| Doc | What |
|---|---|
| `docs/INDEX.md` | This file — roadmap, fleet status |
| `docs/DAEMON-RAILWAY.md` | **Railway cell-16 runbook + sync** |
| `docs/SCRIPT3-PROBLEMS-SOLUTIONS.md` | Problems + fixes (incl. revive) |
| `docs/HANDOFF.md` | Handoff for continuing agent |
| `AGENTS.md` | Agent source of truth |

## Roadmap to all-Lovables mining

### Phase 1 — Prove & lock single-miner stability ✅ DONE (ongoing harden)
- [x] cell-16 via `daemon.py --mode full`
- [x] Health + proxy-404 revive path
- [x] Auth-bridge wait, IDB timeouts, chat save_trio, revive vs token lock
- [x] Browser restart after 3 failed revives
- [ ] 24h continuous green without revive thrash

### Phase 2 — Project factory (script2 per session)
- [ ] script2 `--mode template` for sessions missing projects
- [ ] Verify with `stable_browser.py --shot`
- [ ] Register in GitHub DB

### Phase 3 — Fleet rollout (34 sessions)
- [ ] Rescue → project → deploy daemon `--mode full` per cell
- [ ] Verify Worker alive + md5 sync to master

### Phase 4 — Operations
- [ ] Bridge capacity at 34 workers
- [ ] Cookie hygiene via daemon token refresh

## TODO list (ordered)
1. [ ] Monitor cell-16 for 24h stability
2. [ ] Rescue remaining 33 sessions
3. [ ] Script2 for verified projects
4. [ ] Deploy daemon to each cell
5. [ ] Bridge load test 10 → 34
