# Daemon on Railway (cell-16) — runbook

**Updated:** 2026-09-24  
**Code on cell must match** `daemon.py` + `miner_injector.py` on `master`.  
**Canonical md5:** `daemon.py` = `c5c3ed9ba763d6a481823ac9555f9c9c` · `miner_injector.py` = `28bf95d3a03e4ad3326e99b54841e7fe`  

**Status:** cells **13 / 16 / 28 / 35** mining forever (`lean_sup`, Worker alive). Doc gate = `doc('nproc')`.

Fleet map / sprint: [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)  
**Who is mining:** [`FLEET-LIVE.md`](FLEET-LIVE.md) (cell-16 locked to Railway `sessions/session-2`)

**`window.doc` lives on `https://{project}.lovableproject.com/term`** (Build a debug terminal bridge). Daemon navigates Preview lovableproject iframe → `/term`, then requires **`doc('nproc')`** (stdout) before inject. Homepage / bare `/term` URL alone is **not** enough.

**One-shot fleet probe:** `CHIMERA_DOC_MARK=1` + `CHIMERA_DOC_MARK_ROUNDS=6` → writes `/app/work/DOC_MARK.txt` (`OK`|`NOT_RUNNING`) and exits. Do **not** set this on mining cells.

---

## Auth revive (refresh_token — no Railway password login)

Cells run with `CHIMERA_SKIP_IDB=1` (in-page IDB put/evaluate hangs while Lovable SPA holds the DB). Auth wall recovery:

1. Read disk `indexeddb.json` (must contain Firebase `refresh_token` + real fkey `firebase:authUser:{apiKey}:[DEFAULT]`)
2. Mint new `access_token` via Google `securetoken` API (**Python**, not `page.evaluate`)
3. **Virgin browser context** + `add_init_script` IDB inject (proven; reuse of a context that already loaded lovable.dev fails)
4. Copy cookies into the daemon context → goto project

Password/`do_login` is **last resort** only when refresh_token is missing/invalid.

**Save trio** (OnKernel / local rescue / account create): always persist `cookies.json` + `localstorage.json` + `indexeddb.json` via `automation-toolkit/src/lovable/session_state.save_full_state` (and `revive_via_refresh_token` for silent revive). Never overwrite a good `indexeddb.json` with an empty extract.

Toolkit: `load_session_with_rescue.py` tries in-page refresh, then virgin-context `revive_via_refresh_token`, then password rescue.

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
│   ├── cookies → LS; SKIP_IDB=1 (hydrate)
│   ├── Auth wall → refresh_token revive (Google API + virgin ctx) → else do_login
│   ├── Composer hunt: wait (no reload); CDP hung ×3 → fresh tab
│   ├── Wake + inject into chat Preview lovableproject Shell
│   │     navigate iframe → /term; wait real doc('nproc'); inject confirms sysoptd
│   └── Health every 40–60s (in place — no page reload)
│         human Bezier mouse + light type + tiny prompt
│         popup → close Cancel/X (NO reload)
│         shell check: alive → skip; dead → soft reinject (no reload)
│         fail×6 → fresh tab (browser stays up)
└── NEVER exit full mode
```

**OK lines:**  
`Presence poke ok` · `Presence prompt: sent` · `Worker confirmed running` · `Worker alive (probe: N@…) — skip inject` · `Preview healthy` · `Next check in 40s` · `Auth revived via refresh_token`

**Heal lines:**  
`Popup: closed` · `Shell/worker soft-dead … confirm` · `Revive: iframe soft path (no reload)` · `fresh tab (browser stays up)` · `Cycle #N — same browser, fresh tab` · `Google refresh_token → new access_token OK`

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
| Auth / private project wall | `ensure_authed` → **refresh_token first** → `do_login` last |
| Inject picks cold `id-preview` | Prefer `lovableproject.com` + working `doc('nproc')` |
| Bare preview tab → auth-bridge | Stolen sessioned URL only; else skip to health |
| IDB restore/save wedges CDP | `CHIMERA_SKIP_IDB=1` on hydrate; revive uses virgin ctx + init-script |
| Cold `shell_worker_status` before composer | Skipped — wedges CDP while SPA hydrates |
| Composer miss | Wait (no reload); reload was skeleton death spiral |
| CDP evaluate TimeoutError / tab wedge | Fresh tab in **same** browser (not hard kill) |
| Browser process actually dead | Relaunch Chromium (last resort) |
| Inject hung / empty reply | Verify `sysoptd` procs before claiming success |

Details: `SCRIPT3-PROBLEMS-SOLUTIONS.md` (problems 20+; **#37** refresh_token revive).
