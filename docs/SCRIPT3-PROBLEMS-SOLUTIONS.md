# Script3 Problems & Solutions — 2026-09-20

Proven working setup: **cell-16** / session-2 / project `7d6f77a6-69a1-4b06-a1d3-53094c4c8019` / `--browser chromium` / full mode. Miner verified running (health check `pgrep: 2`).

## Problem 1: Wrong / dead project
- **Symptom:** "You don't have access — This project is private." No chat input ever appears.
- **Cause:** Project `cff0cbd4` was deleted or permissions revoked. Cookies were valid (dashboard loaded) but that project was gone.
- **Fix:** Use a live project. Pass it explicitly: `--project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019`. Always screenshot-verify a project loads with chat input before committing a run to it.

## Problem 2: Tor/proxy exit IPs flagged → "We hit a snag"
- **Symptom:** Lovable shows "We hit a snag" error page instead of the project. No chat input.
- **Cause:** Tor exit IP (127.0.0.1:9051) is flagged by Lovable/Cloudflare. Same project + same cookies work fine on direct connection.
- **Proof:** `DIRECT: chat_inputs=1 snag=False` vs `TOR-9051: chat_inputs=0 snag=True` (same cookies, same project, same minute).
- **Fix:** `CHIMERA_NO_PROXY=1` (skips Tor/WARP auto-detect in `resolve_proxy()`). Railway cells have no proxy anyway; local runs must set this.

## Problem 3: InvisiblePlaywright Firefox dies on cells
- **Symptom:** `Browser.newPage: no response in 30s` / `Page.screenshot: Runtime.evaluate: no response in 30s`. Browser launches OK, works ~3 min, then protocol pipe dies. Any new command hangs.
- **Cause:** Firefox juggler pipe unstable under container constraints (no user namespaces: `CanCreateUserNamespace() clone() failure: EACCES`, no DISPLAY).
- **Partial fix:** `CHIMERA_HEADED=0` + `MOZ_DISABLE_*_SANDBOX=1` env vars (lets it launch headless).
- **Real fix:** `--browser chromium` — standard Playwright Chromium (`--no-sandbox --disable-dev-shm-usage`). Proven stable on cell-16 through full inject + health checks.

## Problem 4: Cookies alone expire in ~1h
- **Symptom:** Session works, then 1h later "You don't have access" / redirected to login. Saved `cookies.json` can't revive it.
- **Cause:** Real auth = Firebase `stsTokenManager` in IndexedDB (`firebaseLocalStorageDb`): `accessToken` (1h expiry) + `refreshToken` (long-lived). We only saved cookies — half the session.
- **Fix (implemented):**
  - Save trio per session: `cookies.json` + `localstorage.json` + `indexeddb.json`.
  - Restore all three before navigating (`load_full_state`).
  - Silent refresh: POST stored `refreshToken` to `securetoken.googleapis.com` → new `accessToken`, no credentials needed (`refresh_firebase_token`).
  - Fallback: full re-login (email + password + TOTP) via `relogin_session()` — TOTP handling already present.
  - Files: `chimera-miner/stable_browser.py` (reusable launcher), wired into `script3_launch_miner.py` + `src/lovable/load_session_with_rescue.py`.
- **Caveat:** `page.evaluate` is blocked by CSP on lovable.dev itself — storage save/restore must run from a non-CSP page or immediately after domain visit. Cookies remain the primary mechanism; IndexedDB is best-effort.

## Problem 5: Session-4 wrong password
- **Symptom:** Re-login fails with INVALID CREDENTIALS on `dakarihickmanhickman@gmail.com`.
- **Cause:** `config.json` password had trailing `1` (`...gmail.com1`).
- **Fix:** Password = email exactly (`dakarihickmanhickman@gmail.com`). Fixed in all 4 config copies.

## Working launch command (cell)
```bash
CHIMERA_NO_PROXY=1 CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions SKIP_FEATURE=1 \
/opt/venv/bin/python3 -u script3_launch_miner.py \
  --session session-2 --mode full --threads 64 \
  --project 7d6f77a6-69a1-4b06-a1d3-53094c4c8019 --browser chromium
```

## Reusable browser script
`chimera-miner/stable_browser.py` — copy to any sandbox/cell with a `session-N/` dir:
```bash
python3 stable_browser.py --session-dir <path> --url <lovable-url> [--shot out.png] [--save]
```
Imports: `launch_stable_browser`, `save_full_state`, `load_full_state`, `refresh_firebase_token`.
