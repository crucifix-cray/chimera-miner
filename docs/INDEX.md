# CHIMERA INDEX — Roadmap & Fleet Status

**Updated:** 2026-09-22 ~00:20 UTC

## Where we are now
- **1 miner LIVE:** cell-16 / session-2 / project `7d6f77a6` / `daemon.py --mode full` / Chromium.
- **Self-heal:** simple revive (refresh chat → wake → wait → preview → inject) + never-exit browser cycles.
- **Live md5:** `13d5b7cb4b8b6961f2acd561aba2ad67` (`5492fdf`).
- **Canonical runbook:** `docs/DAEMON-RAILWAY.md`.
- Sandbox still drops occasionally; daemon recovers. Short gaps expected; permanent stop is a bug.
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app` (never 0ef2).

## Architecture (current daemon)

```
daemon.py --mode full  (never exits)
├── Browser cycle #N
│   ├── Chromium → cookies → LS/IDB
│   ├── wake → wait window.doc → inject → save_trio(chat)
│   └── Health (~180s):
│         dead → refresh chat → wake → wait → preview → inject
│         fail×3 or crash → next Browser cycle
└── main() while True wraps everything
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
