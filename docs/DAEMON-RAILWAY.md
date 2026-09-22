# Daemon on Railway (cell-16) — runbook

**Updated:** 2026-09-22  
**Code on cell must match** `daemon.py` + `miner_injector.py` on `master`.  
**Live md5:** `daemon.py` = `13d5b7cb4b8b6961f2acd561aba2ad67` · `miner_injector.py` = `c69482d1db5be44b36554bb37f07fa7a`  
**Commit:** `5492fdf` (never-exit + simple revive)  

Fleet map / sprint: [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)

---

## Service IDs

| Item | Value |
|---|---|
| Railway project | `340b7baa-d67f-42ae-8c58-fd803b75dc72` |
| Environment | `801b5148-b8e5-445a-a9e5-a813998e5f9d` |
| Service | `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` (cell-16) |
| SSH key | `automation-toolkit/sessions/session-2/.ssh/cellkey` |
| CLI auth | `HOME=/home/alan/Documents/railways/sessions/session-2` |
| Workdir | `/app/work/chimera-miner/` |
| Session trio | `/app/work/scripts/sessions/session-2/` |
| Log | `/app/work/daemon_s2.log` |
| Python | `/opt/venv/bin/python3` |

**Launch:**
```bash
cd /app/work/chimera-miner
nohup env CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions DISPLAY=:99 \
  /opt/venv/bin/python3 -u daemon.py --session session-2 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 \
  --browser chromium --mode full \
  >> /app/work/daemon_s2.log 2>&1 &
```

- Lovable session: `session-2`  
- Project: `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`  
- Bridge: `wss://chimera-bridge-production-0703.up.railway.app`  

This is a Railway **service** (persistent). Do not use sandboxes for the daemon.

---

## Sync after push

```bash
curl -fsSL -o /app/work/chimera-miner/daemon.py \
  https://raw.githubusercontent.com/crucifix-cray/chimera-miner/master/daemon.py
# kill exact PID of /opt/venv/bin/python3 -u daemon.py — never pkill -f
# relaunch (above)
md5sum /app/work/chimera-miner/daemon.py
```

Also sync `miner_injector.py` when it changes.

---

## Behavior

```text
Outer forever (main + run_daemon)
├── Browser cycle #N
│   ├── Chromium (CHIMERA_NO_PROXY=1)
│   ├── cookies → LS + IDB (timeouts)
│   ├── wake chat → preview until window.doc
│   ├── start worker cmd (inject_miner) → save_trio(chat)
│   └── Health (~180s / ~30s on fail)
│         DEAD → refresh chat → wake → wait → preview → inject
│         fail×3 or crash → end cycle → relaunch
└── NEVER exit full mode
```

**OK lines:** `Worker alive (probe: N)` · `Preview healthy`  
**Heal lines:** `Revive: refresh chat → wake → wait → preview → inject` · `Browser cycle #N`  

Preview shells still die sometimes; gaps are normal. Permanent stop is not.

---

## SSH

```bash
export HOME=/home/alan/Documents/railways/sessions/session-2
unset RAILWAY_TOKEN HTTP_PROXY HTTPS_PROXY
railway ssh -p 340b7baa-… -e 801b5148-… -s 46ab5f8c-… -i ~/.ssh/cellkey -- \
  'tail -40 /app/work/daemon_s2.log'
```

---

## Failure cheat sheet

| Symptom | What daemon does |
|---|---|
| proxy-404 / nodoc | Simple revive |
| No chat composer | Reload/goto chat up to 5 rounds |
| Token vs revive race | `page_lock` |
| Trio wiped | Only save from chat page |
| Hang on `load` | `wait_until=commit` + timed eval |
| Console “lovable” only | Require `window.doc` |
| Browser/script crash | Outer cycle relaunch |

Details: `SCRIPT3-PROBLEMS-SOLUTIONS.md`.
