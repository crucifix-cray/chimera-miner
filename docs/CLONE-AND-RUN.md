# CLONE-AND-RUN — stand up a new mining cell

**Updated:** 2026-09-24  
**Goal:** copy what works on cells **13 / 16 / 28 / 35** onto a new Railway cell without rediscovering the stack.

**Canonical code (local repo = truth):**
| File | md5 |
|---|---|
| `daemon.py` | `237dd7a2eaed994f69a9c0ceeb93bddd` |
| `miner_injector.py` | `28bf95d3a03e4ad3326e99b54841e7fe` |

**Ops helper:** `ops/cell_ops.py` (SSH / deploy / upload trio / status).  
**Live who-is-mining:** [`FLEET-LIVE.md`](FLEET-LIVE.md) · **daemon detail:** [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md)

---

## 1. Mental model (three layers)

```text
┌─ Lovable account ─────────────────────────────────────────┐
│  automation-toolkit/scripts/sessions/session-L/           │
│    cookies.json + localstorage.json + indexeddb.json      │
│    (indexeddb MUST contain Firebase refresh_token)        │
│    config.json → email, password, totp_secret             │
└───────────────────────────────────────────────────────────┘
         uploaded to cell as scripts/sessions/session-L/

┌─ Railway account (owns the cell service) ─────────────────┐
│  automation-toolkit/sessions/session-R/                   │
│    .railway/config.json  (CLI auth for THAT account)      │
│    .ssh/cellkey          (registered on THAT account)     │
│  services.json maps session-R → service "cell-N"          │
└───────────────────────────────────────────────────────────┘
         SSH: HOME=…/sessions/session-R  +  ssh-add cellkey

┌─ Cell (Railway service cell-N, ~1GB, volume /data) ───────┐
│  /app/work → /data/work                                   │
│  /app/work/chimera-miner/{daemon,miner_injector}.py       │
│  /app/work/lean_sup.sh   (SESS=session-L  PROJ=<uuid>)    │
│  /app/work/scripts/sessions/session-L/  (full trio)       │
│  forever: Xvfb :99 + lean_sup → daemon --mode full --headed│
└───────────────────────────────────────────────────────────┘
```

**One Lovable project = one cell.** Same Lovable cookies can mine two projects only as two cells with different `--project`.

**Proven live map (2026-09-24):**

| Cell | Railway sess | Lov sess | Project | Email |
|---|---|---|---|---|
| 13 | 1 | 2 | `05da1af6-0626-4746-a339-92d7e6b2e3e1` | altonlehman16@… |
| 16 | 2 | 2 | `7d6f77a6-69a1-4b06-a1d3-53094c4c8019` | altonlehman16@… |
| 28 | 6 | 41 | `ce592dc0-eb0f-4500-81ae-2f848840aaac` | jamesmanalodat.e@… |
| 35 | 10 | 50 | `c0bafd1e-33d8-4625-89a4-1250f4755d23` | hellolakanhernand.ez@… |

---

## 2. How the daemon self-handles (do not break)

```text
lean_sup (while true)
  └── daemon.py --mode full --headed
        ├── Chromium headed on DISPLAY=:99 (CHIMERA_FORCE_HEADED=1)
        ├── Hydrate: cookies + LS init-script; SKIP_IDB=1 (no IDB put on boot)
        ├── Auth wall → refresh_token (Google API + virgin ctx) → else password/TOTP
        ├── Wake composer → Preview iframe → Force /term
        ├── Gate: window.doc('nproc') returns stdout  (URL alone ≠ ready)
        ├── Inject Worker into lovableproject /term frame
        ├── save_trio(..., force_idb=True)  ← always pull refresh_token for next time
        └── Health 40–80s forever
              ├── Worker alive → babysit (CRITICAL mem = probe-only, no poke/shots)
              ├── Flaky nodoc under CRITICAL → patience ×4 + remount Preview
              ├── Confirmed dead + DOC back → in-place revive/inject
              ├── Force /term soft timeout → location.assign fallback
              ├── Force /term miss ×3 OR probe timeout ×6 under CRITICAL
              │     → hard-kill Chrome + relaunch (self-heal, no stuck forever)
              └── NEVER fresh-tab under CRITICAL nodoc (that wedges on id-preview)
```

**Env on every mining cell (lean_sup):**
```bash
CHIMERA_NO_PROXY=1
CHIMERA_SKIP_IDB=1          # hydrate skip; download still force_idb=True after inject
CHIMERA_FORCE_HEADED=1
CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions
CHIMERA_SHOT_DIR=/app/work/shots
DISPLAY=:99
# NEVER set CHIMERA_DOC_MARK on mining cells
```

**OK log lines:** `DOC_MARK=OK doc('nproc')` · `Worker injected!` · `refresh_token=YES` · `Worker alive` · `Preview healthy`

---

## 3. Prerequisites for a NEW cell

1. **Railway cell service** already exists (`cell-N`), image boots to `sleep infinity` with `/app/work → /data/work` (see `cell_service` / start.sh pattern).
2. **Railway account folder** at `automation-toolkit/sessions/session-R/` with working `.railway/config.json` + `.ssh/cellkey` registered on that account (`railway ssh keys list` shows `cellkey`).
3. **Lovable trio** at `automation-toolkit/scripts/sessions/session-L/` with `refresh_token` in `indexeddb.json`.
4. **Lovable project UUID** that this account owns (script2 if missing).
5. **Unlocked OnKernel key** for rescue (`/tmp/onk_write_ok.json` tag=`unlocked`, or `KERNEL_API_KEY`).

Inventory of Railway cells: `/home/alan/Documents/railways/services.json`.

---

## 4. Recipe — clone onto a new cell

### A. Rescue Lovable auth (full trio)

```bash
cd /home/alan/Documents/repos/automation-toolkit
export KERNEL_API_KEY='sk_…'   # unlocked OnK key
env -u HTTP_PROXY -u HTTPS_PROXY -u http_proxy -u https_proxy -u ALL_PROXY -u all_proxy \
  PYTHONUNBUFFERED=1 python3 src/lovable/session_refresh.py L
# Expect: FULL STATE saved … (refresh_token=YES)
ls -la scripts/sessions/session-L/{cookies,localstorage,indexeddb,config}.json
```

`session_refresh.py` already calls `save_full_state` (cookies + LS + IndexedDB). Do **not** overwrite a good `indexeddb.json` with an empty dump.

### B. SSH into the cell (correct HOME + key)

```bash
# NEVER set RAILWAY_TOKEN to expired accessToken
# NEVER copy session .railway into ~/.railway
export HOME=/home/alan/Documents/repos/automation-toolkit/sessions/session-R
cd "$HOME"
unset RAILWAY_TOKEN HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
eval "$(ssh-agent -s)"
ssh-add "$HOME/.ssh/cellkey"
railway whoami
railway ssh -s cell-N -- bash -lc 'hostname; ls /app/work'
```

Or use the helper (preferred):

```bash
cd /home/alan/Documents/repos/chimera-miner
python3 ops/cell_ops.py ssh N -- 'hostname; ls /app/work'
```

### C. Bootstrap code + lean_sup + trio

```bash
python3 ops/cell_ops.py bootstrap N \
  --lov L \
  --project PROJECT_UUID \
  --log daemon_rN.log
```

What bootstrap does on the cell:
1. Writes `daemon.py` + `miner_injector.py` under `/app/work/chimera-miner/` (and `/data/work/…`)
2. Writes trio into `/app/work/scripts/sessions/session-L/` (+ `/data` mirror)
3. Writes `/app/work/lean_sup.sh` with `SESS=session-L` `PROJ=<uuid>` `LOG=/app/work/daemon_rN.log`
4. Ensures Xvfb + starts lean_sup if not running
5. Prints md5 + `pgrep` proof

### D. Verify mining

```bash
python3 ops/cell_ops.py status N
# Want: Worker injected / Worker alive / Preview healthy / refresh_token=YES
```

Healthy under CRITICAL mem (~100% cgroup) is **normal** on 1GB headed+Worker — babysit probe-only, do not panic.

---

## 5. Day-2 ops

| Task | Command |
|---|---|
| Status 4 live | `python3 ops/cell_ops.py status 13 16 28 35` |
| Deploy new daemon | `python3 ops/cell_ops.py deploy-daemon 13 16 28 35` then `bounce` |
| Bounce daemon only | `python3 ops/cell_ops.py bounce N` (lean_sup respawns) |
| Re-upload trio | `python3 ops/cell_ops.py upload-trio N --lov L` |
| Tail log | `python3 ops/cell_ops.py ssh N -- 'tail -c 8000 /data/work/daemon_rN.log'` |

**Hard rules:**
- Kill daemon by **exact PID** from `/proc` cmdline — never `pkill -f` patterns that match your SSH command line.
- Do not fresh-tab under CRITICAL nodoc (daemon already prevents this).
- After auth rescue, always confirm `refresh_token=YES` in IndexedDB before upload.

---

## 6. Image / volume layout (cell_service)

Boot `start.sh` pattern:
```bash
mkdir -p /data/work/chimera-miner /data/work/scripts/sessions /data/work/shots
ln -sfn /data/work /app/work
sleep infinity   # lean_sup started via SSH after deploy (or bake into start later)
```

Stack (Playwright/Chromium/venv) lives in the **image**, not the 500MB volume. Volume holds work only.

---

## 7. Failure → self-heal cheat sheet

| Symptom | What happens |
|---|---|
| Auth wall / login | `refresh_token` revive → else OnK `session_refresh` + re-upload trio |
| Stuck `id-preview` / no doc | Force `/term` (+ `location.assign` fallback) |
| CRITICAL nodoc flake | Patience ×4; remount Preview; no fresh-tab |
| Force `/term` miss ×3 | hard-kill Chrome → lean_sup/daemon relaunch |
| Probe timeout spiral ×6 under CRITICAL | hard-kill + relaunch |
| Daemon Python dies | `lean_sup` restarts in 8s |
| Host wiped to sshd only | Redeploy `cell_service` image, then bootstrap again |

---

## 8. Files to keep in sync

| Path | Role |
|---|---|
| `chimera-miner/daemon.py` | Forever miner + self-heal |
| `chimera-miner/miner_injector.py` | Worker start in `/term` |
| `chimera-miner/ops/cell_ops.py` | Clone/run helper |
| `chimera-miner/docs/CLONE-AND-RUN.md` | This playbook |
| `automation-toolkit/src/lovable/session_refresh.py` | OnK 2FA → full trio |
| `automation-toolkit/src/lovable/session_state.py` | `save_full_state` / refresh revive |
| `automation-toolkit/scripts/sessions/session-L/` | Lovable trios |
| `automation-toolkit/sessions/session-R/` | Railway CLI + cellkey |
| `Documents/railways/services.json` | cell-N ↔ session-R map |

When you change daemon self-heal or env rules: update **this doc + md5 table + HANDOFF** in the same change.
