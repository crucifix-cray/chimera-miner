# INDEX — roadmap & fleet status

**Updated:** 2026-09-22  

**Start here for the whole game:** [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)

## Where we are

- **1 cell LIVE:** cell-16 / session-2 / project `7d6f77a6` / `daemon.py --mode full --headed` / Chromium on Xvfb `:99`  
- **Self-heal:** soft iframe revive (no reload first) → soft-confirm nodoc → hard kill if CDP wedged → never-exit browser cycles  
- **Presence:** every ~40s scroll chat + hover/wheel Preview iframe  
- **Live md5:** `daemon.py`=`079db14a…` · `miner_injector.py`=`12e03c80…` (see runbook)  
- **Runbook:** [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md)  
- Prefer chat Preview `lovableproject.com` Shell Sandbox inject (`CHIMERA_SKIP_IDB=1`)  
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app`  

## Architecture (daemon)

```text
daemon.py --mode full --headed  (never exits)
├── Browser cycle #N  (Playwright launch; soft CDP reattach only if attached)
│   ├── Chromium :99 → cookies → LS (SKIP_IDB)
│   ├── Prefer chat iframe lovableproject + doc('pwd') → inject
│   ├── save_trio(chat)
│   └── Health (~40s):
│         presence scroll/hover/wheel
│         soft-confirm nodoc ×2 → iframe soft revive
│         CDP hung → HARD kill → next Browser cycle
│         fail×3 → next Browser cycle
└── main() while True
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
- [x] Headed Xvfb + iframe inject + SKIP_IDB + 40s presence  
- [x] Soft revive / soft-confirm / hard kill on CDP wedge  
- [ ] Shrink revive gaps (duty cycle) — **sprint day 1**

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
