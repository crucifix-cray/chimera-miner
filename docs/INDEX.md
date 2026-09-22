# INDEX — roadmap & fleet status

**Updated:** 2026-09-22  

**Start here for the whole game:** [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)

## Where we are

- **1 cell LIVE:** cell-16 / session-2 / project `7d6f77a6` / `daemon.py --mode full` / Chromium  
- **Self-heal:** refresh chat → wake → wait → preview → start worker; never-exit browser cycles  
- **Live md5:** `13d5b7cb4b8b6961f2acd561aba2ad67` (`5492fdf`)  
- **Runbook:** [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md)  
- Preview shells flap; daemon recovers. Scoreboard = bridge throughput over time  
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app`  

## Architecture (daemon)

```text
daemon.py --mode full  (never exits)
├── Browser cycle #N
│   ├── Chromium → cookies → LS/IDB
│   ├── wake → wait window.doc → start worker → save_trio(chat)
│   └── Health (~180s):
│         dead → refresh chat → wake → wait → preview → inject
│         fail×3 or crash → next Browser cycle
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
- [x] Simple revive + never-exit cycles  
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
