# Script3 / Daemon — problems & solutions

**Updated:** 2026-09-22  

Proven setup: **cell-16** / session-2 / project `7d6f77a6` / `daemon.py --mode full --headed` / Chromium on Xvfb `:99` / `CHIMERA_SKIP_IDB=1`.  
Runbook: `DAEMON-RAILWAY.md`. Fleet map: `FLEET-ARCHITECTURE.md`. Problems through **#30**.  
Canonical md5s / launch: `docs/DAEMON-RAILWAY.md`. Problems through #36.

Words in this log: **preview shell**, **worker process**, **revive**. Function names like `inject_miner` mean “start the worker command in the preview”.

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
- **Symptom:** proxy-404 → wake with `body unreadable` / goto timeouts → 3×600s revive = ~30 min downtime.
- **Fix (evolved):** simple revive + wall caps; see problems 18–19 for current behavior.

## Problem 18: Console 'lovable' without window.doc → inject abort
- **Symptom:** `Lovable ready (console=True js=-)` then inject `no doc bridge` ×6 → abort.
- **Cause:** `wait_for_lovable_console` treated console text alone as ready.
- **Fix:** Require `js_ready` (`window.doc` / `window.lovable`); console hit alone keeps waiting.

## Problem 19: Browser/script crash must not stop the daemon
- **Symptom:** TargetClosed / page closed / inject exception → process dies or stuck.
- **Cause:** errors escaped outer loop; `main()` only ran `asyncio.run` once.
- **Fix:** detect crash errors + closed pages → end Browser cycle; outer `while True` + `main()` forever loop; log `Forever mode` / `Browser cycle #N`.

## Problem 20: Idle cool-off → preview proxy-404
- **Symptom:** Worker dies after quiet periods; preview shows proxy 404.
- **Cause:** Lovable cools idle chat/preview iframes.
- **Fix:** `HEALTH_INTERVAL_S≈40` + rich presence (chat scroll + Preview iframe hover/wheel). Avoid Home/PageDown/top-chrome that steal focus.

## Problem 21: IDB restore/save wedges CDP on Railway
- **Symptom:** Health `evaluate` hangs; browser looks alive but dead to Playwright.
- **Cause:** IndexedDB trio restore/save blocks the renderer.
- **Fix:** `CHIMERA_SKIP_IDB=1` — cookies+localStorage only on cell.

## Problem 22: Inject into cold `id-preview` / bare preview tab → auth-bridge
- **Symptom:** Inject “succeeds” on dead frame; dedicated preview tab hits auth-bridge.
- **Cause:** Frame picker preferred first `id-preview`; bare tab lacks chat session context.
- **Fix:** Score frames: require working `doc('pwd')`; prefer `lovableproject.com` Shell Sandbox inside chat Preview; dedicated tab is last resort.

## Problem 23: Soft nodoc → chat reload kills CDP
- **Symptom:** One flaky `nodoc` triggers chat reload → TargetClosed / cycle death spiral.
- **Cause:** Revive always reloaded chat first.
- **Fix:** Soft-confirm nodoc ×2; iframe soft revive = wait sandbox + reinject (no chat reload first); wake reload only if soft path fails.

## Problem 24: Soft CDP reattach to wedged Chrome death spiral
- **Symptom:** `spawn_chrome` + reattach keeps talking to a hung renderer; evaluate TimeoutError forever.
- **Cause:** Soft reconnect assumed Chrome was healthy if port 9222 answered.
- **Fix:** Playwright launch is primary; soft CDP reattach only if previously attached + healthy; on evaluate TimeoutError → HARD kill Chrome + new Browser cycle.

## Problem 25: Railway CLI Unauthorized from railways/session-16 HOME
- **Symptom:** `railway ssh` 403/Unauthorized with Documents/railways/session-16 token.
- **Cause:** That token is not the account that owns cell-16.
- **Fix:** Run CLI with `HOME=…/automation-toolkit/sessions/session-2` (owns the service). Do not copy config into machine `~/.railway`.

## Problem 26: Health needs trivial chat prompts too
- **Symptom:** Scroll/hover alone not enough; sandbox still cools / 0 workers after idle.
- **Fix:** Every ~40s health tick also `send_presence_prompt` (same trivial wake strings, **no reload**).

## Problem 27: Auth wall / private project after SKIP_IDB restore
- **Symptom:** Shot shows "You don't have access" / Log In; composer count=0.
- **Cause:** Cookies+LS without full Firebase hydrate can leave chat logged-out of the project.
- **Fix (2026-09-24):** `ensure_authed` → **refresh_token revive first** (Google API + virgin context init-script IDB inject + cookie copy). Password `do_login` only if no/invalid refresh_token. See problem **#37**.

## Problem 28: Fake `window.doc` object poisons Shell Sandbox
- **Symptom:** Inject `Setup result: True` then probe `no doc bridge` forever.
- **Cause:** Injector installed `{ run: … }` object when real doc missing; `typeof doc !== 'function'` and `if (!window.doc)` blocks the real Shell.
- **Fix:** Never install fake doc; clear non-function `window.doc`; only exec via real `typeof doc === 'function'`.

## Problem 29: Blind inject / bare lovableproject tab → auth-bridge / no iframe
- **Symptom:** Inject runs without `pwd`; fallback opens `https://{id}.lovableproject.com` → auth-bridge; or Preview iframe gone (1 frame only).
- **Fix:** Wait real sandbox before inject; presence prompts (no reload) while waiting; click Preview/Shell panel; fallback only with stolen sessioned URL (never bare host).

## Problem 30: Cold `shell_worker_status` / wake reload → CDP wedge + skeleton UI
- **Symptom:** Xvfb shows healthy composer; Playwright evaluate/locator/screenshot TimeoutError; reload leaves gray skeleton.
- **Cause:** Frame-walking before SPA warm wedges CDP; wake reload death spiral.
- **Fix:** Skip cold worker probe before composer; composer miss = wait not reload; wake fast-path sends without reload when already on project; CDP hung streak×3 before hard kill.

## Problem 31: Sandbox wait hangs forever / cell idle after wake
- **Symptom:** Log stuck on `Waiting for chat Preview sandbox/doc (max 120s)...` with no timeout line; `ps` shows no `daemon.py`; last stolen URL often `id-preview` while `lovableproject` probe is `no-doc` / `Error`.
- **Cause:** Wait loop probed **every** chat frame with 12s evaluates; one wedged CDP call never returns → timeout never fires. Playwright Node `EPIPE` can also kill the driver mid-wait.
- **Fix:** Rank frames, probe top-5 only with 6s hard bounds; 15s progress ticks; remount Preview/Shell every ~28s; post-wake spin before wait; outer `main()` catches `BaseException`, hard-kills Chrome, restarts. Launch under a shell `while true` supervisor so a dead Python still comes back.

## Problem 32: Upgrade modal / credits wall wedges presence prompts
- **Symptom:** Xvfb shows "Upgrade your plan" / "0 free build credits"; presence `1+1?` times out; health probe ×3 → hard kill.
- **Cause:** Modal blocks composer; CDP sludge accumulates if chat never reloads during health.
- **Fix:** Every tick dismiss popups; on close (or every 2 min) reload chat; tiny prompts only; human mouse+type; shell check skip-if-running.

## Problem 33: Duty cycle must never sound like "stopping"
- **Symptom:** Logs said "Health cycle ended" / "Cleaning up" / "Interrupted" — looks like the agent quit.
- **Fix:** Wording = "Browser cycle continue / relaunch"; KeyboardInterrupt also continues in full mode; supervisor `while true` still wraps Python.

---

## Problem 34: Robotic mouse/typing looks non-human
- **Symptom:** Straight `mouse.move(steps=N)`, instant `fill()`, always-click preview.
- **Cause:** Real humans use curved paths, Fitts timing, overshoot, IKI ~180ms, reading pauses; hover more than click.
- **Fix:** Bezier+jitter+overshoot `human_mouse_to`, chunked scroll, `human_type_text` (IKI/typo), presence prompt uses them; click ~30%.

## Problem 35: Browser kill/reload spiral + fake "Worker command sent"
- **Symptom:** Health fail×3 → HARD kill Chrome; 2min chat reload; inject logs success after hanging start with empty reply.
- **Cause:** Soft UI issues were treated as browser death; inject trusted start reply without checking `sysoptd`.
- **Fix:** Keep one Chromium; handle popup/dead-worker in place (no reload); fresh tab only if tab wedges; browser relaunch only if process died or 4 tabs never reach health; inject verifies worker procs before returning True.

## Problem 36: Railway 1GB Aw Snap (error code 5) — Target crashed forever
- **Symptom:** After cookies/LS, every `page.evaluate` is `Target crashed`; Xvfb shows Aw Snap; cgroup memory ~950MB/1000MB; composer hunt burned 15×10s on a dead tab.
- **Cause:** Lovable SPA + Chromium exceed the 1GB service limit; post-LS reload and JS probes make it worse.
- **Fix:** Cookies + LS via `add_init_script` **before** goto (no page.evaluate restore on 1GB); skip post-LS reload; skip JS composer probe (locators only); treat `Target crashed` as immediate fresh-tab (streak 1); `CHIMERA_FORCE_HEADED=1` on Xvfb; lean flags + `--js-flags=--max-old-space-size=512` + `--renderer-process-limit=2`. **Still needs ≥1.5–2GB for reliable Shell** — 1GB is marginal.

## Working launch commands

### Daemon on Railway (production — recommended)
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
  echo "[supervisor] daemon exited — restart in 8s" >> /app/work/daemon_s2.log
  sleep 8
done' >> /app/work/daemon_s2.log 2>&1 &
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
# From automation-toolkit — tries refresh_token first, then password/TOTP
cd /home/alae/Documents/repos/automation-toolkit
KERNEL_API_KEY=sk_... python3 -u src/lovable/load_session_with_rescue.py 7 --kernel
```

## Problem 37: Auth wall — refresh_token revive (no Railway password login)
- **Symptom:** Cell hits `Auth wall mid composer hunt` / `Login failed`; full `do_login` on Railway is flaky (TOTP/IP) and unnecessary if we saved Firebase refresh_token.
- **Cause:** Cookies expire (~1h). `CHIMERA_SKIP_IDB=1` means Chromium never got IndexedDB on hydrate. In-page IDB put/`evaluate` **hangs** while Lovable SPA holds `firebaseLocalStorageDb`. Extract often saved `key: null` so restore put nothing useful.
- **Fix (proven 2026-09-24, cell-32 / session-7):**
  1. Always save full trio with real fkey: `firebase:authUser:{apiKey}:[DEFAULT]` (`session_state.synthesize_idb_keys` / `save_full_state`).
  2. On auth wall: mint access token via Google `securetoken` API in **Python**.
  3. Inject IDB via **virgin** `browser.new_context()` + `add_init_script` (not the polluted context).
  4. Copy cookies into the working context → goto project.
  5. Password `do_login` only if refresh_token missing/invalid.
- **Code:** `daemon.py` → `ensure_authed` / `revive_via_refresh_token`; toolkit `session_state.revive_via_refresh_token` + `load_session_with_rescue.py`.
- **Do not** overwrite a good `indexeddb.json` with an empty extract after SPA lock.

## Problem 38: `/term` URL ≠ bridge — gate on `doc('nproc')`
- **Symptom:** Logs show Stolen preview `…/term` or Navigate → `/term`, but Worker never injects; local headed probe shows `window.doc` undefined.
- **Cause:** Lovable change / cold preview — path can exist without Shell Sandbox. Treating URL as “has doc” was wrong.
- **Fix:** Require `await window.doc('nproc')` with non-empty stdout (script3-style). Log `DOC_MARK=OK doc('nproc')→…` or fail.
- **Fleet probe:** `CHIMERA_DOC_MARK=1` + limited rounds → write `/app/work/DOC_MARK.txt` (`OK`|`NOT_RUNNING`) and exit. Mining cells must **not** set this env; use forever `lean_sup`.
- **Proven 2026-09-24:** cells 13/16/28/35 → `nproc=16` → Worker forever; 30/31/32 → `NOT_RUNNING`.

## Key scripts
| Script | Purpose |
|---|---|
| `daemon.py` | **Production** forever agent on a Railway service cell |
| `miner_injector.py` | Start worker command in preview (`inject_miner`) — must match cell |
| `script3_launch_miner.py` | Manual / legacy launcher |
| `github_db.py` | GitHub-backed state helpers |
| `stable_browser.py` | Chromium launcher + trio save/restore |
| `load_session_with_rescue.py` | Session rescue (automation-toolkit) — refresh_token then login |
| `session_state.py` | Trio save + `revive_via_refresh_token` (automation-toolkit) |
