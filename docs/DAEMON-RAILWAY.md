# Daemon on Railway (cell-16) — Canonical Runbook

**Updated:** 2026-09-21 ~22:15 UTC  
**Source of truth in repo:** `daemon.py` + `miner_injector.py` on branch `master`  
**Live cell:** hashes of those two files on the box MUST match `master` after each deploy.  
**Live md5:** `daemon.py` = `601feb0d419066b98d930bed9b0940df` · `miner_injector.py` = `c69482d1db5be44b36554bb37f07fa7a`

---

## What runs on the Railway service

| Item | Value |
|---|---|
| Railway project | `340b7baa-d67f-42ae-8c58-fd803b75dc72` |
| Environment | `801b5148-b8e5-445a-a9e5-a813998e5f9d` |
| Service | `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` (cell-16) |
| SSH key | `automation-toolkit/sessions/session-2/.ssh/cellkey` (agent: session-16) |
| Workdir on cell | `/app/work/chimera-miner/` |
| Session trio | `/app/work/scripts/sessions/session-2/` |
| Log | `/app/work/daemon_s2.log` |
| Python | `/opt/venv/bin/python3` |

**Launch command (production):**
```bash
cd /app/work/chimera-miner
nohup env CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions \
  /opt/venv/bin/python3 -u daemon.py --session session-2 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 \
  --browser chromium --mode full \
  > /app/work/daemon_s2.log 2>&1 &
```

**Account / project:**
- Session: `session-2` / `altonlehman16@gmail.com`
- Project: `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`
- Bridge: `wss://chimera-bridge-production-0703.up.railway.app` (in `daemon.py` / `miner_injector.py`)

---

## Repo files that MUST stay in sync with the cell

| File | Role on Railway |
|---|---|
| `daemon.py` | Autonomous miner (full-mode health + revive) — **primary** |
| `miner_injector.py` | `inject_miner()`, worker command builder |
| (session trio, not in chimera-miner git) | `cookies.json` / `localstorage.json` / `indexeddb.json` / `config.json` under sessions dir |

Deploy path used in practice: **base64 pipe of `daemon.py` over `railway ssh`** (reliable).  
Alternate: `curl` raw GitHub `master/daemon.py` on the cell after push.

Verify sync:
```bash
# local
md5sum daemon.py miner_injector.py
# cell
md5sum /app/work/chimera-miner/daemon.py /app/work/chimera-miner/miner_injector.py
```

---

## Daemon behavior (full mode) — current

```
Cold start
├── Chromium headless (CHIMERA_NO_PROXY=1)
├── Load cookies → restore LS + IDB (IDB restore hard-timeout 15s)
├── Open chat → wake prompt (say 'a' / 1+1? / 2+2? / …)  [NOT script2 debug-terminal]
├── Open preview → wait_for_lovable_console
│     (auth-bridge: wait, don't reload-spam; reload uses wait_until=commit)
│     until console 'lovable' OR window.doc / window.lovable
└── inject_miner() → save_trio from chat page → health loop

Health loop (~180s when healthy; ~30s after failed revive)
├── shell_worker_status: proxy-404 / auth-bridge / login / nodoc / probe=0 → DEAD
├── If DEAD → simple revive (serialized vs token refresh, 420s wall):
│     refresh chat → send wake cmd → wait 12s → goto preview → wait doc → inject
│     (retry wake once if no doc; keep looping)
├── Revive fail streak ≥ 3 → browser restart in 5s
└── Token refresh every 40m (skipped while revive lock held; 20s hard timeout)
    save_trio always from chat origin (never preview — preview wipe bug)
```

**Flags:**
- `--mode full` — forever health (production)
- `--mode oneshot` — inject once, exit
- `--headed` / `CHIMERA_HEADED=1` — local diagnose only (not on Railway)

---

## SSH helper

```bash
# From automation-toolkit (dedicated agent + cellkey)
# Or the pattern used in ops:
SOCK=/tmp/agents/cell16.sock
# ssh-add session-2 cellkey → HOME=railways/session-16
railway ssh -p 340b7baa-… -e 801b5148-… -s 46ab5f8c-… -- 'tail -40 /app/work/daemon_s2.log'
```

Success log lines: `Worker alive (probe: N)` + `Preview healthy`.

---

## Known failure modes (see also SCRIPT3-PROBLEMS-SOLUTIONS.md)

| Symptom | Fix in daemon |
|---|---|
| Preview proxy 404 | Full revive: wake → lovable → inject |
| Chat input missing during revive | Always goto chat; re-login; 4 rounds; browser restart after 3 fails |
| Token refresh vs revive race | `page_lock` — refresh skipped during revive |
| save from preview wipes LS/IDB | `save_trio(chat_page)` only |
| reload hangs on `load` | `wait_until="commit"` |
| IDB save/restore hang | 15s timeout, continue |
