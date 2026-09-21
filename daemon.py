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


async def send_wake_prompt(chat_page) -> bool:
    """Send a trivial script3 wake prompt on the chat tab (wakes sandbox)."""
    import random as _rand
    chat_input = None
    for sel in [
        'div[contenteditable="true"][role="textbox"]',
        '[contenteditable="true"]',
        "textarea",
    ]:
        try:
            if await chat_page.locator(sel).count() > 0:
                chat_input = chat_page.locator(sel).first
                break
        except Exception:
            continue
    if not chat_input:
        log("  Wake prompt: chat input not found")
        return False
    prompt = _rand.choice(WAKE_PROMPTS)
    log(f"  Sending wake prompt: '{prompt}'")
    try:
        await chat_page.bring_to_front()
    except Exception:
        pass
    try:
        await chat_input.click(timeout=5000)
    except Exception:
        pass
    await chat_input.fill(prompt)
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
        await chat_page.keyboard.press("Enter")
    log("  Wake prompt sent")
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
    refresh_interval = 40
    while True:
        elapsed = asyncio.get_running_loop().time() - start
        if elapsed > timeout_seconds:
            log(f"  Timeout waiting for lovable console after {timeout_seconds}s")
            return False

        try:
            body = await preview_page.evaluate(
                "() => (document.body && document.body.innerText) || ''"
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
                js_ready = await preview_page.evaluate(
                    """() => {
                        if (window.lovable) return 'lovable-obj';
                        if (window.doc && typeof window.doc === 'function') return 'doc';
                        return '';
                    }"""
                )
            except Exception as e:
                log(f"  ready-check error: {e}")

        # Require preview URL (not auth-bridge) + console/js signal
        if on_preview and not on_auth_bridge and (seen["hit"] or js_ready):
            log(
                f"  Lovable ready (console={seen['hit']} js={js_ready or '-'} "
                f"url={cur_url[:80]}) after {int(elapsed)}s"
            )
            return True

        if on_auth_bridge:
            log(f"  Still on auth-bridge — refreshing ({int(elapsed)}s)")
        elif proxy_dead:
            log(f"  Preview proxy 404 — refreshing ({int(elapsed)}s)")
        else:
            log(f"  Refreshing preview... ({int(elapsed)}s)")

        try:
            # Prefer goto bare project URL if stuck on auth-bridge
            if on_auth_bridge and "return_url=" in cur_url:
                from urllib.parse import urlparse, parse_qs, unquote
                qs = parse_qs(urlparse(cur_url).query)
                ret = unquote((qs.get("return_url") or [""])[0])
                if ret:
                    await preview_page.goto(ret, timeout=30000, wait_until="commit")
                else:
                    await preview_page.reload(timeout=30000)
            else:
                await preview_page.reload(timeout=30000)
        except Exception as e:
            log(f"  Refresh error: {e}")
        await asyncio.sleep(5)
        await asyncio.sleep(refresh_interval)


async def revive_sandbox(chat_page, preview_page, bridge_url: str, threads: int) -> bool:
    """
    Worker/shell dead recovery (script3 style):
    resend wake prompt → refresh preview until lovable console → inject.
    """
    from miner_injector import inject_miner

    log("  Revive: wake prompt + wait lovable console + re-inject")
    await send_wake_prompt(chat_page)
    try:
        await preview_page.bring_to_front()
    except Exception:
        pass
    ready = await wait_for_lovable_console(preview_page, timeout_seconds=300)
    if not ready:
        log("  First wait failed — second wake + wait")
        await send_wake_prompt(chat_page)
        try:
            await preview_page.bring_to_front()
        except Exception:
            pass
        ready = await wait_for_lovable_console(preview_page, timeout_seconds=300)
    if not ready:
        log("  Revive: lovable console never appeared")
        return False
    ok = await inject_miner(preview_page, bridge_url, threads)
    log(f"  Revive inject: {'OK' if ok else 'FAILED'}")
    return bool(ok)


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
        idb = await page.evaluate("""async () => {
            return new Promise((resolve) => {
                try {
                    const req = indexedDB.open('firebaseLocalStorageDb');
                    req.onsuccess = () => {
                        try {
                            const db = req.result;
                            const stores = Array.from(db.objectStoreNames);
                            if (!stores.length) { resolve([]); return; }
                            const tx = db.transaction(stores, 'readonly');
                            const out = [];
                            let pending = stores.length;
                            stores.forEach(sn => {
                                try {
                                    const rq = tx.objectStore(sn).getAll();
                                    rq.onsuccess = () => {
                                        rq.result.forEach(r => out.push({store: sn, key: r.fkey || r.key, value: r.value}));
                                        if (--pending === 0) resolve(out);
                                    };
                                    rq.onerror = () => { if (--pending === 0) resolve(out); };
                                } catch(e) { if (--pending === 0) resolve(out); }
                            });
                        } catch(e) { resolve([]); }
                    };
                    req.onerror = () => resolve([]);
                } catch(e) { resolve([]); }
            });
        }""")
        with open(sdir / "indexeddb.json", "w") as f:
            json.dump(idb, f, indent=2)
        has_ref = any(
            r.get("value", {}).get("stsTokenManager", {}).get("refreshToken")
            for r in idb if isinstance(r.get("value"), dict))
        log(f"  Saved {len(idb)} IndexedDB records, refresh_token={'YES' if has_ref else 'MISSING'}")
    except Exception as e:
        log(f"  IndexedDB save failed: {e}")


async def refresh_firebase_token(page):
    """Refresh Firebase access token via refresh token. Returns True if ok."""
    try:
        result = await page.evaluate("""async () => {
            return new Promise((resolve) => {
                try {
                    const req = indexedDB.open('firebaseLocalStorageDb');
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
                                    if (exp > now + 60000) { resolve({status: 'fresh', exp}); return; }
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
                                            resolve({status: 'refreshed', exp: v.stsTokenManager.expirationTime});
                                        } else { resolve({status: 'failed'}); }
                                    } catch(e) { resolve({status: 'error'}); }
                                    return;
                                }
                            }
                            resolve({status: 'no_token'});
                        };
                        getAll.onerror = () => resolve({status: 'db_error'});
                    };
                    req.onerror = () => resolve({status: 'db_open_failed'});
                } catch(e) { resolve({status: 'error'}); }
            });
        }""")
        status = result.get("status", "unknown")
        if status in ("fresh", "refreshed"):
            log(f"  Token {status} (exp={result.get('exp', '?')})")
            return True
        else:
            log(f"  Token issue: {status}")
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


async def run_daemon(session_id, project_id, browser_type, threads, mode):
    from playwright.async_api import async_playwright
    from miner_injector import inject_miner

    config = load_config_sync(session_id)
    log(f"Session: {session_id} ({config.get('email', '?')})")
    log(f"Project: {project_id}")

    preview_url = f"https://{project_id}.lovableproject.com"
    chat_url = f"https://lovable.dev/projects/{project_id}"

    while True:  # outer forever loop — relaunches browser on catastrophic failure
        pw = await async_playwright().start()
        try:
            # Launch browser
            if browser_type == "chromium":
                browser = await pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                           "--disable-blink-features=AutomationControlled"])
            else:
                browser = await pw.firefox.launch(headless=True)

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
                await send_wake_prompt(chat_page)
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

            # Save state
            await save_trio(context, preview_page, session_id)

            # Run health check loop (this blocks forever in full mode)
            log("Starting health check loop...")
            last_refresh = time.time()

            async def daemon_health_loop():
                """Health: probe worker; on death → wake prompt + lovable wait + inject."""
                iteration = 0
                while True:
                    iteration += 1
                    log(f"Health check #{iteration}...")
                    try:
                        # Check doc bridge (worker alive)
                        try:
                            ready = await preview_page.evaluate(
                                "() => !!(window.doc && typeof window.doc === 'function')")
                            if ready:
                                probe = await preview_page.evaluate("""async () => {
                                    try {
                                        const r = await window.doc("ps -A -o args | grep -c '[s]ysoptd'");
                                        return r && r.stdout !== undefined ? r.stdout.trim() : 'no-probe';
                                    } catch(e) { return 'probe-error'; }
                                }""")
                                # Also treat proxy 404 as dead even if evaluate somehow works
                                try:
                                    body = await preview_page.evaluate(
                                        "() => (document.body && document.body.innerText) || ''")
                                    if "proxy error" in body.lower() and "404" in body:
                                        ready = False
                                        log("  Preview proxy 404 — treating as dead")
                                except Exception:
                                    pass
                            if ready:
                                log(f"  Worker alive (probe: {probe})")
                            else:
                                log("  Worker dead — revive (wake + lovable console + inject)")
                                await revive_sandbox(
                                    chat_page, preview_page, BRIDGE_URL, threads)
                        except Exception as e:
                            log(f"  Probe error: {e}")
                            log("  Probe failed — attempting revive...")
                            try:
                                await revive_sandbox(
                                    chat_page, preview_page, BRIDGE_URL, threads)
                            except Exception as e2:
                                log(f"  Revive error: {e2}")

                        # Check preview health
                        try:
                            url = preview_page.url
                            if "/login" in url:
                                log("  Preview redirected to login!")
                            else:
                                try:
                                    body = await preview_page.evaluate(
                                        "() => (document.body && document.body.innerText) || ''")
                                    if "proxy error" in body.lower() and "404" in body:
                                        log("  Preview unhealthy (proxy 404)")
                                    else:
                                        log("  Preview healthy")
                                except Exception:
                                    log("  Preview healthy")
                        except Exception:
                            log("  Preview unreachable")

                        # Human presence (quick, non-blocking)
                        try:
                            import random as _r
                            await preview_page.mouse.move(_r.randint(100, 800), _r.randint(100, 500))
                            await asyncio.sleep(0.5)
                        except Exception:
                            pass

                    except Exception as e:
                        log(f"  Health check error: {e}")

                    log(f"  Next check in 180s...")
                    await asyncio.sleep(180)

            health_task = asyncio.create_task(daemon_health_loop())

            # Token refresh loop runs alongside
            while not health_task.done():
                await asyncio.sleep(60)
                now = time.time()
                if now - last_refresh >= TOKEN_REFRESH_INTERVAL:
                    log("--- TOKEN REFRESH ---")
                    ok = await refresh_firebase_token(preview_page)
                    if ok:
                        await save_trio(context, preview_page, session_id)
                    last_refresh = now

            # health_check_loop returned — this shouldn't happen in full mode
            # but if it does, restart everything
            log("Health loop exited — restarting in 30s...")
            try:
                await browser.close()
            except Exception:
                pass
            await asyncio.sleep(30)

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
    args = parser.parse_args()

    try:
        asyncio.run(run_daemon(args.session, args.project, args.browser, args.threads, args.mode))
    except KeyboardInterrupt:
        log("Interrupted")


if __name__ == "__main__":
    main()
