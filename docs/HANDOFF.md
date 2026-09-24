# HANDOFF — continue the fleet

**Updated:** 2026-09-24 (self-heal + clone-and-run playbook)

**Start here next time:** [`CLONE-AND-RUN.md`](CLONE-AND-RUN.md) + `ops/cell_ops.py`  
You are continuing **Lovable + Railway cell** automation. Scale = clone the proven cell pattern.

Also read: [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md) · [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md) · [`FLEET-LIVE.md`](FLEET-LIVE.md)

## Already done

- `daemon.py` / `miner_injector.py` — headed Xvfb, chat-iframe inject, presence, soft revive, **auth → refresh_token first**, **doc gate = `doc('nproc')`**, CRITICAL self-heal (Force `/term` + assign fallback + hard-relaunch if stuck)
- **Mining forever:** cells **13, 16, 28, 35** (`lean_sup`, no `CHIMERA_DOC_MARK`)
- Full trios with `refresh_token` for 28 (lov-41) + 35 (lov-50); 13/16 share lov-2
- Toolkit: `session_state.save_full_state` + `session_refresh.py` (OnK) + `revive_via_refresh_token`
- **Canonical md5:** `daemon.py`=`237dd7a2eaed994f69a9c0ceeb93bddd` · `miner_injector.py`=`28bf95d3a03e4ad3326e99b54841e7fe`
- Fleet map: `ops/fleet_map.json` · clone helper: `ops/cell_ops.py`
- Bridge `wss://chimera-bridge-production-0703.up.railway.app`

## Clone a new cell (short)

```bash
# 1) Rescue Lovable trio (OnK unlocked key)
cd /home/alan/Documents/repos/automation-toolkit
KERNEL_API_KEY=sk_… python3 src/lovable/session_refresh.py L   # refresh_token=YES

# 2) Bootstrap cell
cd /home/alan/Documents/repos/chimera-miner
python3 ops/cell_ops.py bootstrap N --lov L --project PROJECT_UUID --railway-session R

# 3) Verify
python3 ops/cell_ops.py status N
```

Full detail + self-heal rules: **[`CLONE-AND-RUN.md`](CLONE-AND-RUN.md)**

## Rules (do not violate)

- `CHIMERA_NO_PROXY=1` + `CHIMERA_SKIP_IDB=1` + `CHIMERA_FORCE_HEADED=1` + `DISPLAY=:99` + `--headed`
- Auth wall: **refresh_token before password**; always `save_trio(..., force_idb=True)` after inject/revive
- Never clobber good `indexeddb.json` with empty extract
- Require real `doc('nproc')` before inject; never fake `window.doc`
- No `CHIMERA_DOC_MARK` on mining cells
- Railway SSH: `HOME=automation-toolkit/sessions/session-R` + `ssh-add .ssh/cellkey` — **never** copy into `~/.railway`; unset `RAILWAY_TOKEN`
- Kill daemon by exact `/proc` cmdline PID — never blind `pkill -f` (matches SSH argv)
- Under CRITICAL nodoc: no fresh-tab (id-preview wedge); Force `/term` then hard-relaunch if stuck

## Key files

| File | Role |
|---|---|
| `docs/CLONE-AND-RUN.md` | **Clone playbook (read this)** |
| `ops/cell_ops.py` | status / ssh / deploy / trio / bootstrap |
| `ops/fleet_map.json` | cell ↔ railway sess ↔ lov sess ↔ project |
| `daemon.py` | Forever agent + self-heal |
| `miner_injector.py` | Worker start in `/term` |

## Next

Bridge+auth remaining cells (23/25/26/30/31/32/36) using the same bootstrap recipe — do not invent a new stack.
