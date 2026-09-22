# Daemon on Railway (cell-16) — Canonical Runbook

**Updated:** 2026-09-22 ~00:20 UTC  
**Source of truth in repo:** `daemon.py` + `miner_injector.py` on branch `master`  
**Live cell:** hashes of those two files on the box MUST match `master` after each deploy.  
**Live md5:** `daemon.py` = `13d5b7cb4b8b6961f2acd561aba2ad67` · `miner_injector.py` = `c69482d1db5be44b36554bb37f07fa7a`  
**Commit:** `5492fdf` — never-exit + simple revive

---

## What runs on the Railway service

| Item | Value |
|---|---|
| Railway project | `340b7baa-d67f-42ae-8c58-fd803b75dc72` |
| Environment | `801b5148-b8e5-445a-a9e5-a813998e5f9d` |
| Service | `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` (cell-16) |
| SSH key | `automation-toolkit/sessions/session-2/.ssh/cellkey` |
| CLI auth | `HOME=/home/alan/Documents/railways/sessions/session-2` (mendo.zakian56) |
| Workdir on cell | `/app/work/chimera-miner/` |
| Session trio | `/app/work/scripts/sessions/session-2/` |
| Log | `/app/work/daemon_s2.log` |
| Python | `/opt/venv/bin/python3` |

**Launch command (production):**
```bash
cd /app/work/chimera-miner
nohup env CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions DISPLAY=:99 \
  /opt/venv/bin/python3 -u daemon.py --session session-2 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 \
  --browser chromium --mode full \
  >> /app/work/daemon_s2.log 2>&1 &
```

**Account / project:**
- Session: `session-2` / `altonlehman16@gmail.com`
- Project: `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`
- Bridge: `wss://chimera-bridge-production-0703.up.railway.app`

---

## Repo files that MUST stay in sync with the cell

| File | Role on Railway |
|---|---|
| `daemon.py` | Autonomous miner (full-mode health + revive) — **primary** |
| `miner_injector.py` | `inject_miner()`, worker command builder |
| (session trio, not in chimera-miner git) | cookies / LS / IDB / config under sessions dir |

**Deploy:** after `git push`, on cell:
```bash
curl -fsSL -o /app/work/chimera-miner/daemon.py \
  https://raw.githubusercontent.com/crucifix-cray/chimera-miner/master/daemon.py
# kill by exact PID of /opt/venv/bin/python3 -u daemon.py — never pkill -f
# then relaunch (see Launch command)
md5sum /app/work/chimera-miner/daemon.py   # must match local master
```

---

## Daemon behavior (full mode) — current

```
Outer forever (main + run_daemon while True)
├── Browser cycle #N
│   ├── Chromium headless (CHIMERA_NO_PROXY=1)
│   ├── cookies → LS + IDB (timeouts)
│   ├── wake chat → preview wait until window.doc
│   ├── inject_miner → save_trio (chat page only)
│   └── Health loop (~180s / ~30s on fail)
│         ├── shell_worker_status → DEAD?
│         ├── YES → simple revive:
│         │     refresh chat → wake cmd → wait 12s → preview → wait doc → inject
│         ├── revive fail ×3 → end cycle → relaunch browser
│         └── page/browser crash → end cycle → relaunch browser
├── Any script/Playwright error → clean up → sleep → next cycle
└── NEVER exit full mode
```

**Expected reality:** Lovable sandbox still dies sometimes (proxy-404 / nodoc / slow page). Daemon recovers via revive or browser cycle. Short 0-worker gaps are normal; permanent stop is not.

**Success log lines:** `Worker alive (probe: N)` + `Preview healthy`  
**Recovery lines:** `Revive: refresh chat → wake → wait → preview → inject` · `Browser cycle #N`

---

## SSH helper

```bash
export HOME=/home/alan/Documents/railways/sessions/session-2
unset RAILWAY_TOKEN HTTP_PROXY HTTPS_PROXY
railway ssh -p 340b7baa-… -e 801b5148-… -s 46ab5f8c-… -i ~/.ssh/cellkey -- \
  'tail -40 /app/work/daemon_s2.log'
```

---

## Known failure modes (see SCRIPT3-PROBLEMS-SOLUTIONS.md)

| Symptom | Fix in daemon |
|---|---|
| Preview proxy 404 / nodoc | Simple revive: refresh chat → wake → preview → inject |
| Chat composer missing | Reload/goto chat up to 5 rounds; no abort-on-eval |
| Token refresh vs revive race | `page_lock` |
| save from preview wipes trio | `save_trio(chat_page)` only |
| reload hangs on `load` | `wait_until="commit"` + timed `_page_eval` |
| Console lovable without doc | Require `window.doc` / `window.lovable` |
| Browser/script crash | Outer cycle relaunch; `main()` while True |
