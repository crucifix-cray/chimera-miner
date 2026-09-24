# INDEX — roadmap & fleet status

**Updated:** 2026-09-24  

- **Start here for the whole game:** [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)
- **Who is mining right now:** [`FLEET-LIVE.md`](FLEET-LIVE.md)

## Where we are

- **Live map:** [`FLEET-LIVE.md`](FLEET-LIVE.md)  
- **Mining now (4):** cells **13, 16, 28, 35** — `doc('nproc')` OK → Worker forever (`lean_sup`, no `CHIMERA_DOC_MARK`)  
- **Doc gate:** real bridge = `window.doc('nproc')` returns stdout (not URL / not `typeof`)  
- **Auth:** refresh_token revive path live; Good28 accounts re-verified LIVE_OK  
- **Not mining yet:** 23, 25, 26, 30, 31, 32, 36 (DOC_NOT_RUNNING / auth / composer)  
- **Code md5:** `daemon.py`=`c5c3ed9ba763d6a481823ac9555f9c9c` · `miner_injector.py`=`28bf95d3a03e4ad3326e99b54841e7fe`  
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
| `FLEET-ARCHITECTURE.md` | **Visuals, sprint, capacity math, script 1–3** |
| `DAEMON-RAILWAY.md` | Cell-16 IDs, launch, sync |
| `SCRIPT3-PROBLEMS-SOLUTIONS.md` | Fixes log |
| `HANDOFF.md` | Continue-here checklist |
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
