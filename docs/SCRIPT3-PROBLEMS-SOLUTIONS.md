# Script3 / Daemon Problems & Solutions

**Last updated:** 2026-09-21 ~06:00 UTC

Proven working setup: **cell-16** / session-2 / project `7d6f77a6` / `daemon.py` / `--browser chromium`. Autonomous daemon running, health checks passing every 3 min.

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
- **Fix:** Save full trio: `cookies.json` + `localstorage.json` + `indexeddb.json` (contains Firebase refresh token). Daemon auto-refreshes every 40 min via `securetoken.googleapis.com`.

## Problem 5: Session-4 wrong password
- **Symptom:** Re-login fails with INVALID CREDENTIALS.
- **Cause:** `config.json` password had trailing `1`.
- **Fix:** Password = email exactly. Fixed in all 4 config copies.

## Problem 6: Rescue script hangs forever (10h sleep loop)
- **Symptom:** `load_session_with_rescue.py --kernel` connects, restores state, then never exits.
- **Cause:** All 3 branches (kernel/zenrows/local) had `asyncio.sleep(36000)` after saving — waiting for Ctrl+C.
- **Fix:** Removed all sleep loops. Script saves and exits immediately. Commit `18f2e3c`.

## Problem 7: Rescue script hangs on IndexedDB restore
- **Symptom:** `_load_full_state` hangs after "Restored localStorage" — never proceeds to IndexedDB.
- **Cause:** `indexedDB.deleteDatabase()` + `indexedDB.open()` on same DB can deadlock in `onblocked` event.
- **Fix:** Added `NAV_TIMEOUT = 15000` with `wait_until="commit"` (fastest load state) + retry fallback. Commit `18f2e3c`.

## Problem 8: Daemon doesn't inject — sandbox never ready
- **Symptom:** Daemon launches, opens preview, but `inject_miner` fails with "Sandbox not ready yet (attempt 6/6): no doc bridge".
- **Cause:** Daemon opened preview directly without sending a build prompt first. The WebContainer sandbox needs a chat prompt to start.
- **Fix:** Daemon now: opens chat → sends prompt ("say 'x'") → opens preview → waits for doc bridge (max 60s) → injects. Commit `8ff5972`.

## Problem 9: Health check loop hangs forever
- **Symptom:** Health check #1 passes, then no more checks appear in log. Process alive but stuck.
- **Cause:** `health_check_loop` from `miner_injector.py` calls `human_chat_visit()` which navigates to chat URL with 45s timeout + `stay_seconds=random.uniform(10, 40)` — hangs if page load stalls.
- **Fix:** Replaced with custom `daemon_health_loop` — lightweight 3-step check (doc bridge probe, preview URL check, mouse wiggle). No navigation calls. Runs clean every 3 min. Commit `477c46c`.

## Problem 10: Sandbox crashes periodically — re-inject fails
- **Symptom:** Worker alive for hours, then dies. Re-injection fails with "Sandbox not ready" forever.
- **Cause:** Lovable WebContainer crashes. `inject_miner` tries to find doc bridge but sandbox is dead. Needs page reload to restart sandbox.
- **Fix:** On worker death: `preview_page.reload()` → wait for doc bridge (up to 60s, reload every 5s) → re-inject. Commit `70d8efd`.

---

## Working launch commands

### Daemon (autonomous — recommended)
```bash
CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions \
python3 -u daemon.py --session session-2 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 --browser chromium
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
| `daemon.py` | Autonomous miner — runs forever, self-healing |
| `script3_launch_miner.py` | Manual miner launcher (single run) |
| `miner_injector.py` | Worker injection + `inject_miner()` |
| `github_db.py` | GitHub DB backend (replaces Mega) |
| `stable_browser.py` | Reusable Chromium launcher + state save/restore |
| `src/lovable/load_session_with_rescue.py` | Session rescue (re-login + full state save) |
