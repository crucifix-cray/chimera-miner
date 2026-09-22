# AGENTS.md — Chimera fleet (Lovable + Railway automation)

**Last updated:** 2026-09-22  
**Maintained by:** Cursor agent (local)  
**Read first:** [`docs/FLEET-ARCHITECTURE.md`](docs/FLEET-ARCHITECTURE.md) · [`docs/DAEMON-RAILWAY.md`](docs/DAEMON-RAILWAY.md)

Grug source of truth for the next human or coding agent. Keep language plain. Prefer **worker / cell / bridge / throughput** in prose even when filenames say otherwise.

---

## What this system does

Automate **Lovable.dev** preview shells (WebContainers) from **Railway Ubuntu services** (“cells”):

1. **Script 1** — create Railway accounts, verify **services** (not sandboxes), write state  
2. **Script 2** — create Lovable projects (template / remix / accept), store project IDs  
3. **Daemon** (`daemon.py`) — wake chat, open preview, start worker command, health + revive forever  

Control plane: **WSS bridges**. Sprint map + math: `docs/FLEET-ARCHITECTURE.md`.

---

## Current status (2026-09-22)

- **1 cell LIVE:** cell-16 / Lovable `session-2` / project `7d6f77a6…` / `daemon.py --mode full` / Chromium headed  
- **Heal path:** soft presence → wait real `window.doc` → inject; crashes → **Browser cycle #N**; shell supervisor restarts dead Python  
- **Canonical md5:** `daemon.py` = `88b072001e15aa6df480cf1eaee225af` · `miner_injector.py` = `9441b4768314cab9ad7dbc94089bf13a`  
- **Bridge:** `wss://chimera-bridge-production-0703.up.railway.app`  
- Preview shells still drop sometimes; daemon recovers. Short gaps expected.  
- ~34 Lovable sessions on disk path; scale goal in fleet doc (~1K services + ~1K sessions)

---

## Daemon behavior (short)

1. Chromium + session trio (cookies / localStorage / IndexedDB; IDB timeouts)  
2. Trivial chat wake (`say 'a'`, `1+1?`, …) — **not** script2 “debug terminal” prompts  
3. Preview until `window.doc` / `window.lovable` (console text alone is not enough)  
4. `inject_miner()` = **start worker command** in preview shell; `save_trio` from **chat** origin only  
5. Health: dead shell → simple revive; fail ×3 or crash → relaunch browser cycle  
6. Token refresh ~40m under `page_lock`  
7. `main()` `while True` — full mode does not exit  

Cell must run the **same** `daemon.py` + `miner_injector.py` bytes as `master`.

---

## Repos

| Repo | Purpose | Notes |
|------|---------|-------|
| `automation-toolkit` | Script 1, sessions, credentials docs | Private |
| `chimera-miner` (this tree) | Script 2/3, daemon, fleet docs | Active |
| `system-optimizer-daemon` | Worker binary / start cmd target | Private |
| `invisible_playwright` | Stealth browser helpers | Optional |

Paths on this machine often under `/home/alan/Documents/repos/…`.

---

## Critical rules

- `CHIMERA_NO_PROXY=1` on Lovable browser work  
- `--browser chromium` + `--mode full` on Railway cells  
- Railway **services** for daemons; sandboxes are not production homes  
- `save_trio` only from `lovable.dev` chat page  
- Kill cell processes by **exact PID** — never `pkill -f` matching SSH  
- No secrets in git; credentials live outside this doc  
- After daemon push: `curl` raw GitHub file onto cell → restart → `md5sum` match  

---

## Tree (useful files)

```text
chimera-miner/
├── daemon.py                 # Forever fleet agent on a cell
├── miner_injector.py         # Start worker cmd + helpers
├── script2_remix_link.py     # Project factory
├── script3_launch_miner.py   # Legacy one-shot launcher
├── stable_browser.py         # Headed diagnose / shots
├── docs/
│   ├── FLEET-ARCHITECTURE.md # Map, sprint, math  ← start here
│   ├── DAEMON-RAILWAY.md     # Cell-16 IDs + launch
│   ├── HANDOFF.md
│   ├── INDEX.md
│   └── SCRIPT3-PROBLEMS-SOLUTIONS.md
└── …
```

---

## Script 2 notes

Modes: `template`, `remix`, `accept` (`accept` often most robust with invites).  
Wake prompts for daemon ≠ script2 build prompts.

## Script 1 notes

Needs: provider failover, OnKernel-first where useful, mobile/human-like, **service verify**, state writes. Details in fleet architecture doc.
