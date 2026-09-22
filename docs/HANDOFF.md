# HANDOFF — continue the fleet

**Updated:** 2026-09-22  

You are continuing **Lovable + Railway cell** automation. One cell is live and self-healing. Scale is the job.

**Read first:**
1. [`FLEET-ARCHITECTURE.md`](FLEET-ARCHITECTURE.md) — map, sprint, math  
2. [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md) — cell IDs, launch, md5  

## Already done

- `daemon.py` on cell-16 — headed Xvfb, chat-iframe inject, 40s presence, soft revive, never-exit cycles  
- Session-2 / project `7d6f77a6-69a1-4b06-a1d3-53094c4c8019`  
- Live md5 `daemon.py`=`079db14a40b6a778dcf1d37c3cd3ef1a` · `miner_injector.py`=`12e03c8023f67358e978462b5a00c78a`  
- Bridge `wss://chimera-bridge-production-0703.up.railway.app`  
- Problems log through #25 in `SCRIPT3-PROBLEMS-SOLUTIONS.md`  

## Rules (do not violate)

- `CHIMERA_NO_PROXY=1` + `CHIMERA_SKIP_IDB=1` + `DISPLAY=:99` + `--headed` on cells  
- Chromium + `--mode full` on cells  
- Daemons live on Railway **services**, not sandboxes  
- Prefer inject into chat Preview `lovableproject.com` iframe (not a 2nd tab)  
- `save_trio` from chat page only (cookies+LS when SKIP_IDB)  
- Kill by exact PID — never `pkill -f` on SSH  
- Wake = trivial prompts only  
- Soft revive = wait sandbox + reinject (no chat reload first); hard kill if CDP evaluate hung  
- Crash → Browser cycle relaunch; full mode never exits  
- After push: curl `daemon.py` + `miner_injector.py` to cell, restart, verify md5  
- Railway CLI: `HOME=…/automation-toolkit/sessions/session-2` (do not copy into `~/.railway`)  
- No secrets in commits; see automation-toolkit credentials doc  

## Credentials (pointers only)

- OnKernel / ZenRows / GH: `automation-toolkit` credentials doc — **do not paste into git**  
- Bridge URL: production `0703` host (see runbook)  
- SSH: `automation-toolkit/sessions/session-2/.ssh/cellkey` + runbook project/env/service IDs  
- Railway CLI login: `HOME=…/automation-toolkit/sessions/session-2`  

## Sessions still needing rescue / projects

See architecture doc for scale targets. Local list often includes sessions 4+ (skip burned session-1).

```bash
cd /home/alae/Documents/repos/automation-toolkit
CHIMERA_NO_PROXY=1 python3 -u src/lovable/load_session_with_rescue.py N --kernel
```

## Deploy daemon to a cell

1. Rescue / verify session trio  
2. Ensure Lovable project exists (script 2)  
3. `git push` then on cell: curl raw `master/daemon.py` + `miner_injector.py`  
4. Restart with launch cmd in `DAEMON-RAILWAY.md`  
5. Log: `Presence poke ok` + `Worker alive` + `Preview healthy` + `Next check in 40s`  

## Key files

| File | Role |
|---|---|
| `daemon.py` | Forever agent on a cell |
| `miner_injector.py` | Builds/starts worker command in preview |
| `script2_remix_link.py` | Project factory |
| `script3_launch_miner.py` | Legacy launcher |
| `docs/FLEET-ARCHITECTURE.md` | Vision + sprint |

## Next sprint lanes (pick one)

**A — Duty cycle:** measure bridge throughput 1h; harden revive so gaps shrink  
**B — State + script 1:** schema, service verify, provider failover  
**C — Script 2 batch:** fill project IDs for ready sessions  

Do not start all three at once.
