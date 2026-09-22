# Daemon on Railway (cell-16) — runbook

**Updated:** 2026-09-22  
**Code on cell must match** `daemon.py` + `miner_injector.py` on `master`.  
**Live md5:** `daemon.py` = `079db14a40b6a778dcf1d37c3cd3ef1a` · `miner_injector.py` = `12e03c8023f67358e978462b5a00c78a`  

Fleet map / sprint: [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md)

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

**Launch:**
```bash
cd /app/work/chimera-miner
nohup env CHIMERA_NO_PROXY=1 CHIMERA_SKIP_IDB=1 \
  CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions \
  CHIMERA_SHOT_DIR=/app/work/shots \
  DISPLAY=:99 PYTHONUNBUFFERED=1 \
  /opt/venv/bin/python3 -u daemon.py --session session-2 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 \
  --browser chromium --mode full --headed \
  >> /app/work/daemon_s2.log 2>&1 &
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
├── Browser cycle #N  (Playwright launch primary; CDP soft-reattach only if attached)
│   ├── Chromium headed on :99, remote-debugging-port=9222
│   ├── cookies → LS; SKIP_IDB=1 (IDB restore/save wedges CDP on Railway)
│   ├── Prefer inject into chat Preview iframe (lovableproject.com Shell Sandbox)
│   │     steal URL → wait window.doc('pwd') → inject_miner (score lovableproject ≫ id-preview)
│   │     fallback: dedicated preview tab only if iframe path fails
│   ├── save_trio(chat) — cookies+LS only when SKIP_IDB=1
│   └── Health every ~40s
│         presence: scroll chat + hover/wheel Preview iframe (no Home/PageDown/top-chrome)
│         soft-confirm nodoc ×2 before revive
│         iframe soft revive = wait sandbox + reinject (NO chat reload first)
│         CDP evaluate hung → HARD kill Chrome (reattach to wedged renderer is useless)
│         fail×3 → end cycle → relaunch
└── NEVER exit full mode
```

**OK lines:**  
`Presence poke ok (chat+preview: scroll/hover/wheel/…)` · `Worker alive (probe: N@…lovableproject.)` · `Preview healthy` · `Next check in 40s`

**Heal lines:**  
`Shell/worker soft-dead … confirm 1/2` · `Revive: iframe soft path (no reload)` · `HARD kill (renderer wedged)` · `Browser cycle #N`

---

## SSH

```bash
export HOME=/home/alae/Documents/repos/automation-toolkit/sessions/session-2
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
| Idle cool-off / proxy-404 risk | 40s rich presence (scroll/hover/wheel) |
| Flaky `nodoc` | Soft re-probe + confirm ×2 before revive |
| Sandbox dead (confirmed) | Iframe soft revive (no reload) → wake reload only if soft fails |
| Inject picks cold `id-preview` | Frame score prefers `lovableproject.com` + working `pwd` |
| Bare preview tab → auth-bridge | Prefer chat iframe; fallback tab last resort |
| IDB restore/save wedges CDP | `CHIMERA_SKIP_IDB=1` |
| CDP evaluate TimeoutError | HARD kill Chrome + new Browser cycle |
| Playwright-launched Chrome | Soft CDP reconnect N/A (close kills it); cycle relaunches |
| Token vs revive race | `page_lock` |
| Trio wiped | Only save from chat page |

Details: `SCRIPT3-PROBLEMS-SOLUTIONS.md` (problems 20+).
