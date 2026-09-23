# Daemon on Railway (cell-16) — runbook

**Updated:** 2026-09-23  
**Code on cell must match** `daemon.py` + `miner_injector.py` on `master`.  
**Canonical md5:** `daemon.py` = `228be8b060b77341a6d87b8ffe06e31a` · `miner_injector.py` = `b5033cbdcafd3fe2320b14489c54ef13`  

**Status:** cell-16 — **one Chromium kept up**; issues handled in place (no reload); fresh tab only if a tab wedges; browser relaunch last resort.

Fleet map / sprint: [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)  
**Who is mining:** [`FLEET-LIVE.md`](FLEET-LIVE.md) (cell-16 locked to Railway `sessions/session-2`)

---

## Service IDs

| Item | Value |
|---|---|
| Railway project | `340b7baa-d67f-42ae-8c58-fd803b75dc72` |
| Environment | `801b5148-b8e5-445a-a9e5-a813998e5f9d` |
| Service | `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` (cell-16) |
| SSH key | `automation-toolkit/sessions/session-2/.ssh/cellkey` |
| CLI auth HOME | `automation-toolkit/sessions/session-2` (run from that path — do **not** copy into `~/.railway`) |
| Workdir | `/app/work/chimera-miner/` |
| Session trio | `/app/work/scripts/sessions/session-2/` |
| Log | `/app/work/daemon_s2.log` |
| Shots | `/app/work/shots/` |
| Python | `/opt/venv/bin/python3` |
| Display | `Xvfb :99` (headed Chromium) |

**Launch** (shell supervisor — restarts if Python dies after Node EPIPE):
```bash
cd /app/work/chimera-miner
nohup bash -c 'while true; do
  env CHIMERA_NO_PROXY=1 CHIMERA_SKIP_IDB=1 CHIMERA_FORCE_HEADED=1 \
    CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions \
    CHIMERA_SHOT_DIR=/app/work/shots \
    DISPLAY=:99 PYTHONUNBUFFERED=1 \
    /opt/venv/bin/python3 -u daemon.py --session session-2 \
    --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 \
    --browser chromium --mode full --headed
  ec=$?
  echo "[$(date -u +%H:%M:%S)] supervisor: daemon exited $ec — restart in 8s" \
    >> /app/work/daemon_s2.log
  sleep 8
done' >> /app/work/daemon_s2.log 2>&1 &
```

- Lovable session: `session-2`  
- Project: `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`  
- Bridge: `wss://chimera-bridge-production-0703.up.railway.app`  

This is a Railway **service** (persistent). Do not use sandboxes for the daemon.

---

## Sync after push

```bash
# from automation-toolkit/sessions/session-2 as HOME:
curl -fsSL -o /app/work/chimera-miner/daemon.py \
  https://raw.githubusercontent.com/crucifix-cray/chimera-miner/master/daemon.py
curl -fsSL -o /app/work/chimera-miner/miner_injector.py \
  https://raw.githubusercontent.com/crucifix-cray/chimera-miner/master/miner_injector.py
# kill exact PID of /opt/venv/bin/python3 -u daemon.py — never pkill -f
# relaunch (above)
md5sum /app/work/chimera-miner/daemon.py /app/work/chimera-miner/miner_injector.py
```

---

## Behavior

```text
Outer forever (main + run_daemon)
├── ONE Chromium kept up (headed :99)
│   ├── Cycle #N = same browser, fresh tab (only if tab wedged)
│   │     browser relaunch ONLY if process died OR 4 fresh tabs never reached health
│   ├── cookies → LS; SKIP_IDB=1
│   ├── Auth wall → do_login + goto project (no hard kill)
│   ├── Composer hunt: wait (no reload); CDP hung ×3 → fresh tab
│   ├── Wake + inject into chat Preview lovableproject Shell
│   │     wait real doc('pwd'); inject confirms sysoptd running (not just "sent")
│   └── Health every 40–60s (in place — no page reload)
│         human Bezier mouse + light type + tiny prompt
│         popup → close Cancel/X (NO reload)
│         shell check: alive → skip; dead → soft reinject (no reload)
│         fail×6 → fresh tab (browser stays up)
└── NEVER exit full mode
```

**OK lines:**  
`Presence poke ok` · `Presence prompt: sent` · `Worker confirmed running` · `Worker alive (probe: N@…) — skip inject` · `Preview healthy` · `Next check in 40s`

**Heal lines:**  
`Popup: closed` · `Shell/worker soft-dead … confirm` · `Revive: iframe soft path (no reload)` · `fresh tab (browser stays up)` · `Cycle #N — same browser, fresh tab`

---

## SSH

```bash
export HOME=/home/alan/Documents/repos/automation-toolkit/sessions/session-2
cd "$HOME"
unset RAILWAY_TOKEN HTTP_PROXY HTTPS_PROXY https_proxy http_proxy
railway ssh -p 340b7baa-d67f-42ae-8c58-fd803b75dc72 \
  -e 801b5148-b8e5-445a-a9e5-a813998e5f9d \
  -s 46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d \
  -i "$HOME/.ssh/cellkey" -- \
  'tail -40 /app/work/daemon_s2.log'
```

Do **not** copy `.railway/config.json` into the machine’s real `~/.railway`. Run with that session directory as `HOME`.

Note: `Documents/railways/session-16` CLI token may be 403 — cell SSH uses toolkit **session-2** Railway account (owns the service).

---

## Failure cheat sheet

| Symptom | What daemon does |
|---|---|
| Idle cool-off / proxy-404 risk | 40s presence poke + trivial chat prompt |
| Flaky `nodoc` | Soft re-probe + confirm ×2 before revive |
| Sandbox dead (confirmed) | Iframe soft revive (no reload) → wake only if soft fails |
| No `window.doc` yet | Wait + presence + remount; **do not** blind-inject |
| Stuck on `Waiting for sandbox/doc` forever | Ranked probes + ticks; supervisor restarts Python if process dies |
| Fake `window.doc` object | Injector clears it; never re-installs stub |
| Auth / private project wall | `detect_auth_wall` → `do_login` → goto project |
| Inject picks cold `id-preview` | Prefer `lovableproject.com` + working `pwd` |
| Bare preview tab → auth-bridge | Stolen sessioned URL only; else skip to health |
| IDB restore/save wedges CDP | `CHIMERA_SKIP_IDB=1` |
| Cold `shell_worker_status` before composer | Skipped — wedges CDP while SPA hydrates |
| Composer miss | Wait (no reload); reload was skeleton death spiral |
| CDP evaluate TimeoutError / tab wedge | Fresh tab in **same** browser (not hard kill) |
| Browser process actually dead | Relaunch Chromium (last resort) |
| Inject hung / empty reply | Verify `sysoptd` procs before claiming success |

Details: `SCRIPT3-PROBLEMS-SOLUTIONS.md` (problems 20+).
