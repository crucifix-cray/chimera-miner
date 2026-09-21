# Script3 / Daemon Problems & Solutions

**Last updated:** 2026-09-21 ~18:00 UTC

Proven working setup: **cell-16** / session-2 / project `7d6f77a6` / `daemon.py --mode full` / `--browser chromium`.  
Railway details: `docs/DAEMON-RAILWAY.md`.

---

## Problem 1: Wrong / dead project
- **Symptom:** "You don't have access — This project is private." No chat input ever appears.
- **Cause:** Project deleted or permissions revoked. Cookies valid but project gone.
- **Fix:** Use a live project. Pass explicitly: `--project 7d6f77a6-...`. Screenshot-verify before committing.

## Problem 2: Tor/proxy exit IPs flagged → "We hit a snag"
- **Symptom:** Lovable shows "We hit a snag" error page. No chat input.
- **Cause:** Tor exit IP flagged by Lovable/Cloudflare.
- **Fix:** `CHIMERA_NO_PROXY=1` (always, for all Lovable traffic).

## Problem 3: Firefox dies on containers
- **Symptom:** `Browser.newPage: no response in 30s`. Works ~3 min, then pipe dies.
- **Cause:** Firefox juggler pipe unstable under container constraints.
- **Fix:** `--browser chromium` everywhere. Standard Playwright Chromium with `--no-sandbox --disable-dev-shm-usage`.

## Problem 4: Cookies alone expire in ~1h
- **Symptom:** Session works, then 1h later redirected to login.
- **Cause:** Firebase `accessToken` expires in 1h. `refreshToken` is long-lived but we weren't saving it.
- **Fix:** Save full trio: `cookies.json` + `localstorage.json` + `indexeddb.json`. Daemon auto-refreshes every 40 min. **Always save from chat page**, not preview.

## Problem 5: Session-4 wrong password
- **Symptom:** Re-login fails with INVALID CREDENTIALS.
- **Cause:** `config.json` password had trailing `1`.
- **Fix:** Password = email exactly. Fixed in all 4 config copies.

## Problem 6: Rescue script hangs forever (10h sleep loop)
- **Symptom:** `load_session_with_rescue.py --kernel` connects, restores state, then never exits.
- **Cause:** All 3 branches had `asyncio.sleep(36000)` after saving.
- **Fix:** Removed sleep loops. Script saves and exits.

## Problem 7: IndexedDB restore / save hangs
- **Symptom:** Startup stuck after localStorage; or post-inject hung on IDB save.
- **Cause:** `deleteDatabase` onblocked / IDB open never resolves.
- **Fix:** `asyncio.wait_for(..., 15)` on restore and save; continue without IDB if timed out.

## Problem 8: Daemon doesn't inject — sandbox never ready
- **Symptom:** `inject_miner` fails with "no doc bridge".
- **Cause:** Preview opened without waking sandbox via chat.
- **Fix:** Wake prompt → `wait_for_lovable_console` → inject. Wake = trivial prompts only (NOT script2 debug-terminal).

## Problem 9: Health check loop hangs forever
- **Symptom:** Health #1 passes, then silence.
- **Cause:** Old `health_check_loop` navigated away with long sleeps.
- **Fix:** Custom `daemon_health_loop` — probe only, no chat navigation in the happy path.

## Problem 10: Sandbox crashes — reload-only revive fails
- **Symptom:** Worker dies; re-inject never gets `doc`.
- **Cause:** WebContainer needs a chat wake, not bare reload.
- **Fix:** `revive_sandbox`: wake chat → refresh until console `lovable` → inject.

## Problem 11: Auth-bridge treated as ready / reload-loop
- **Symptom:** Stuck on auth-bridge; or false-ready then inject fails.
- **Cause:** Reloading interrupts auth handoff; auth-bridge URL mistaken for preview ready.
- **Fix:** Wait on auth-bridge (no reload-spam); require lovableproject URL off auth-bridge; escape via `return_url` after ~90s; preview reload `wait_until=commit`.

## Problem 12: Preview `reload(wait_until=load)` hangs
- **Symptom:** Log stuck on “Refreshing preview…” / 30s timeout.
- **Cause:** lovableproject often never fires full `load`.
- **Fix:** All preview reloads/gotos use `wait_until="commit"`.

## Problem 13: save_trio from preview wipes trio
- **Symptom:** After inject, LS/IDB become `{}` / refresh_token=MISSING.
- **Cause:** Firebase state lives on `lovable.dev`, not `*.lovableproject.com`.
- **Fix:** `save_trio(context, chat_page, …)` only; token refresh also on chat page.

## Problem 14: Revive can't find chat input / token race
- **Symptom:** Endless `chat input missing`; token refresh `Execution context was destroyed`.
- **Cause:** Stuck SPA page + concurrent token refresh navigating same tab; login wall.
- **Fix:** Always `goto` chat_url each wake round; re-login on wall; more selectors; `page_lock` so refresh never overlaps revive; **3 revive fails → full browser restart**.

## Problem 15: Probe says alive while preview is proxy 404
- **Symptom:** Health logs Worker alive then Preview unhealthy.
- **Cause:** Zombie `window.doc` on a 404 body / race.
- **Fix:** `shell_worker_status` fails closed on proxy-404, auth-bridge, login, nodoc, probe=0, and proxy-404-zombie recheck.

## Problem 16: Revive hung — chat Loading/Dashboard + token refresh holds lock
- **Symptom:** After proxy-404, wake rounds show `Dashboard`/`Recents` or `Loading...`; no composer; Chromium in `D` state; token refresh logs span ~17 min; revive never reaches fail-streak restart.
- **Cause:** `page.evaluate` / IndexedDB refresh had no hard timeout → held `page_lock`; SPA stuck on shell; skip-link present but unused.
- **Fix:** `_page_eval` + 20s token refresh timeout; click "Skip to chat input"; revive wall-clock; log when waiting for `page_lock`.

## Problem 17: Fail-slow revive keeps fleet at 0 workers for ~30 min
- **Symptom:** proxy-404 → wake with `body unreadable` / goto timeouts → 3×600s revive = ~30 min downtime; empty body falsely treated as Loading → reload+goto pileup; `?_wake=` cache-bust interrupted navigations.
- **Cause:** Too-tolerant wake/revive; false Loading detection on empty eval; overlapping reload/goto.
- **Fix:** `REVIVE_WALL_S=120`, `FAIL_STREAK_RESTART=2`, abort wake after 2 dead evals/gotos, no cache-bust query, no reload-on-empty, health probe 30s timeout, browser restart in 5s; probe TimeoutError skips revive.

---

## Working launch commands

### Daemon on Railway (production — recommended)
```bash
CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions \
/opt/venv/bin/python3 -u daemon.py --session session-2 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 \
  --browser chromium --mode full \
  > /app/work/daemon_s2.log 2>&1 &
```
See `docs/DAEMON-RAILWAY.md` for project/env/service IDs and md5 sync.

### Local headed diagnose
```bash
CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=.../scripts/sessions \
python3 -u daemon.py --session session-2 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 \
  --browser chromium --mode full --headed
```

### Manual script3 (legacy)
```bash
CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions SKIP_FEATURE=1 \
python3 -u script3_launch_miner.py \
  --session session-2 --mode full --threads 64 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 --browser chromium
```

### Session rescue
```bash
CHIMERA_NO_PROXY=1 python3 load_session_with_rescue.py 2 --kernel
```

## Key scripts
| Script | Purpose |
|---|---|
| `daemon.py` | **Production** autonomous miner (Railway) |
| `miner_injector.py` | Worker injection + `inject_miner()` — must match cell |
| `script3_launch_miner.py` | Manual miner launcher (legacy) |
| `github_db.py` | GitHub DB backend |
| `stable_browser.py` | Reusable Chromium launcher + state save/restore |
| `src/lovable/load_session_with_rescue.py` | Session rescue |
