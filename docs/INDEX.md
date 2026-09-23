# INDEX — roadmap & fleet status

**Updated:** 2026-09-22  

**Start here for the whole game:** [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)

## Where we are

- **cell-16 LIVE:** session-2 / project `7d6f77a6` — supervisor + headed daemon (`DAEMON-RAILWAY.md`)  
- **Code:** headed Xvfb, chat-iframe inject, 40s presence+prompt, auth-wall, soft revive, no fake `window.doc`, ranked sandbox wait (problem 31)  
- **Canonical md5:** `daemon.py`=`228be8b0…` · `miner_injector.py`=`b5033cbd…` (see runbook)  
- **Open blocker:** 1GB cgroup → Aw Snap error 5; need ≥1.5–2GB for reliable Shell  
- Prefer chat Preview `lovableproject.com` Shell Sandbox; require real `doc('pwd')` before inject  
- Launch with `CHIMERA_FORCE_HEADED=1` on Xvfb  
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app`  

## Architecture (daemon)

```text
daemon.py --mode full --headed  (never exits)
├── Browser cycle #N  (Playwright launch; soft CDP reattach only if attached)
│   ├── Chromium :99 → cookies → LS (SKIP_IDB) → auth-wall? login
│   ├── Composer wait (no reload) → wake (prefer no-reload)
│   ├── Wait real window.doc → inject (ranked probes + ticks; no fake stub)
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
