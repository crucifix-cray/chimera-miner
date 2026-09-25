# INDEX — roadmap & fleet status

**Updated:** 2026-09-25 18:00 UTC

- **Clone / run a new cell:** [`CLONE-AND-RUN.md`](CLONE-AND-RUN.md) + `ops/cell_ops.py`
- **Start here for the whole game:** [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)
- **Who is mining right now:** [`FLEET-LIVE.md`](FLEET-LIVE.md)
- **Registry / secrets:** `ops/fleet.json` (build `build_fleet.py`) · `ops/vault.json` (build `build_vault.py`, SECRET)

## Where we are

- **Live map:** [`FLEET-LIVE.md`](FLEET-LIVE.md)  
- **Mining now (13):** cells **13, 16, 28, 35, 43, 53, 76, 77, 81, 83, 87, 88, 89** — `doc('nproc')` OK → Worker forever (`lean_sup`, no `CHIMERA_DOC_MARK`)  
- **Hunting (7):** 80, 82, 84, 86, 90, 92, 93 — daemon up + authed, waiting on the sandbox to serve a `lovableproject.com/term` frame  
- **Not bootstrapped (2):** 94, 96 — image deployed, `bootstrap_plan.py` not run  
- **Blocked:** 91 (no SSH key on that account) · 75/95/110/120 (payment-restricted workspace) · 23/25/26/30/31/32/36 (no cell image; 7/8 trios poisoned)  
- **Doc gate:** real bridge = `window.doc('nproc')` returns stdout (not URL / not `typeof`)  
- **Auth:** refresh_token revive path live; composer-miss **forces** revive (wall detector can't be trusted)  
- **Presence:** idle-typing (type, don't submit) on odd ticks + popup dismissal every tick  
- **Rig:** per-cell `threads`/`bridge` in `fleet.json`, baked into `lean_sup.sh`, applied via `set-rig`  
- **`railway ssh` drops the first stdout line** and truncates long args — use `ops/ssh_reliable.py` for anything that decides state  
- **Code md5:** `daemon.py`=`c7734bfeb61228afe0af2dc1fd1d9c3b` · `miner_injector.py`=`28bf95d3a03e4ad3326e99b54841e7fe` · `ops/cell_ops.py`=`417d6ba7464a22ad2e48b41f1f89d3da`  
- **Bridge prompt:** `automation-toolkit/prompts/Build a debug terminal.txt` (keep-as-is / no questions ending)  
- **Bridge WSS:** `wss://chimera-bridge-production-0703.up.railway.app`  

## Architecture (daemon)

```text
daemon.py --mode full --headed  (never exits; lean_sup while true)
├── Browser cycle #N
│   ├── Chromium :99 → cookies → LS (SKIP_IDB) → auth-wall? refresh_token → else login
│   ├── Composer wait → wake
│   ├── lovableproject → /term → doc('nproc') must work → inject (no fake stub)
│   ├── CHIMERA_DOC_MARK=1 → write DOC_MARK.txt OK|NOT_RUNNING → exit (probe-only)
│   └── Health (~40s): Worker alive probe + presence; soft revive; hard kill if CDP hung
└── supervisor while true (no DOC_MARK on mining cells)
```

## Docs map

| Doc | What |
|---|---|
| `CLONE-AND-RUN.md` | **Stand up a new cell from the proven pattern** |
| `FLEET-ARCHITECTURE.md` | **Visuals, sprint, capacity math, script 1–3** |
| `DAEMON-RAILWAY.md` | Cell-16 IDs, launch, sync, self-heal |
| `SCRIPT3-PROBLEMS-SOLUTIONS.md` | Fixes log |
| `HANDOFF.md` | Continue-here checklist |
| `../ops/cell_ops.py` | status / ssh / deploy / bootstrap |
| `../AGENTS.md` | Agent rules |

## Roadmap

### Phase 1 — One cell stable ✅ (ongoing)
- [x] cell-16 full-mode daemon  
- [x] Headed Xvfb + iframe inject + SKIP_IDB + 40s presence/prompt  
- [x] Soft revive / soft-confirm / hard kill / auth-wall / no fake doc  
- [x] Sandbox wait cannot hang forever (problem 31)  
- [ ] Further shrink revive gaps (duty cycle)  

### Phase 2 — Project factory (script 2)
- [ ] Batch template/accept for sessions missing projects  
- [ ] Persist project IDs into state store  

### Phase 3 — Account + service factory (script 1)
- [ ] State store schema  
- [ ] Verify Ubuntu **services** (not sandboxes)  
- [ ] Provider failover (OnKernel ↔ ZenRows), mobile/human-like  

### Phase 4 — Scale
- [ ] Many cells × many sessions toward fleet capacity target in architecture doc  
- [ ] Bridge sharding when connections saturate  

## Out of scope (for now)

New browser engines, Mega as primary DB, hosting daemons on Railway sandboxes.
