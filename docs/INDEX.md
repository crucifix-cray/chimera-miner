# INDEX — roadmap & fleet status

**Updated:** 2026-09-23 (stop point)  

- **Start here for the whole game:** [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)
- **Who is mining right now:** [`FLEET-LIVE.md`](FLEET-LIVE.md)

## Where we are

- **Live map:** [`FLEET-LIVE.md`](FLEET-LIVE.md) — **STOPPED** fleet push; honest status only  
- **Mining now:** cell-16 (locked) + cell-13 only  
- **5 daemons up, not mining:** cells 23/28/30/31/35 — OnKernel had bridge earlier; cell `/term` still **no-doc**  
- **4 left for bridge:** cells **25 / 26 / 32 / 36**  
- **OnKernel:** default key billing-blocked for create; use unlocked farm `KERNEL_API_KEY`; org ≤5 concurrent  
- **Code:** headed Xvfb, **`lovableproject → /term`** before `doc('pwd')`, md5 `daemon.py`=`c05b8a9e…` · `miner_injector.py`=`b5033cbd…`  
- **Bridge prompt:** `automation-toolkit/prompts/Build a debug terminal.txt` via `inject_fleet_projects.py`  
- **Bridge WSS:** `wss://chimera-bridge-production-0703.up.railway.app`  

## Architecture (daemon)

```text
daemon.py --mode full --headed  (never exits)
├── Browser cycle #N  (Playwright launch; soft CDP reattach only if attached)
│   ├── Chromium :99 → cookies → LS (SKIP_IDB) → auth-wall? login
│   ├── Composer wait (no reload) → wake (prefer no-reload)
│   ├── lovableproject → /term → wait real window.doc → inject (no fake stub)
│   ├── save_trio(chat)
│   └── Health (~40s):
│         presence scroll/hover/wheel + trivial chat prompt
│         soft-confirm nodoc ×2 → iframe soft revive
│         CDP hung → HARD kill → next Browser cycle
│         fail×3 → next Browser cycle
└── main() while True + shell supervisor while true
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
