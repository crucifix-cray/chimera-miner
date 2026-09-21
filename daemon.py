#!/usr/bin/env python3
"""
Autonomous Miner Daemon
Launches miner, runs health checks, refreshes Firebase tokens, auto-recovers.
Runs forever. No manual intervention needed.

Usage:
  CHIMERA_NO_PROXY=1 python3 -u daemon.py --session session-2 --project <id> --browser chromium
  CHIMERA_NO_PROXY=1 python3 -u daemon.py --session session-2 --project <id> --browser chromium --threads 64
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

SESSIONS_DIR = Path(os.environ.get(
    "CHIMERA_SESSIONS_DIR",
    "/home/alan/Documents/repos/automation-toolkit/scripts/sessions"))
BRIDGE_URL = "wss://chimera-bridge-production-0703.up.railway.app"

HEALTH_INTERVAL = 180       # 3 min between health checks
TOKEN_REFRESH_INTERVAL = 2400  # 40 min between token refreshes (safe margin before 1h expiry)
MAX_RECOVERY_ATTEMPTS = 3
RECOVERY_BACKOFF = [30, 60, 120]  # seconds between recovery attempts


def ts():
    return time.strftime("%H:%M:%S", time.localtime())


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


async def load_cookies(session_id):
    sdir = SESSIONS_DIR / f"session-{session_id}"
    with open(sdir / "cookies.json") as f:
        return json.load(f)


async def load_config(session_id):
    sdir = SESSIONS_DIR / f"session-{session_id}"
    with open(sdir / "config.json") as f:
        return json.load(f)


async def save_trio(context, page, session_id):
    """Save cookies + localStorage + IndexedDB to disk."""
    sdir = SESSIONS_DIR / f"session-{session_id}"
    # Cookies
    cookies = await context.cookies()
    with open(sdir / "cookies.json", "w") as f:
        json.dump(cookies, f, indent=2)
    log(f"  Saved {len(cookies)} cookies")
    # localStorage
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
    # IndexedDB
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
            log(f"  Token refresh issue: {status}")
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

    # Check if already logged in
    if "/dashboard" in page.url or "/projects" in page.url:
        log("  Already logged in")
        return True

    # Email
    try:
        await page.locator('input[placeholder="Email"]').fill(email)
        await page.locator('[data-testid="auth-submit-button"]').click()
        await page.wait_for_timeout(3000)
    except Exception as e:
        log(f"  Email step failed: {e}")
        return False

    # Password
    try:
        await page.locator('input[placeholder="Password"]').fill(password)
        await page.locator('[data-testid="auth-submit-button"]').click()
        await page.wait_for_timeout(6000)
    except Exception as e:
        log(f"  Password step failed: {e}")
        return False

    # Check for 2FA
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

    # Check result
    url = page.url
    if "/login" in url:
        try:
            body = await page.evaluate("() => document.body.innerText.slice(0, 200)")
        except Exception:
            body = ""
        if "Log in" in body[:200]:
            log("  Login failed — still on login page")
            return False

    log("  Login successful")
    return True


class MinerDaemon:
    def __init__(self, session_id, project_id, browser_type, threads, mode):
        self.session_id = session_id
        self.project_id = project_id
        self.browser_type = browser_type
        self.threads = threads
        self.mode = mode
        self.config = None
        self.browser = None
        self.context = None
        self.page = None  # preview page
        self.chat_page = None  # chat tab
        self.worker_running = False
        self.last_token_refresh = 0
        self.last_health_check = 0
        self.recovery_count = 0
        self.running = True

    async def setup(self):
        """Launch browser, restore state, navigate to project."""
        from playwright.async_api import async_playwright
        self.pw = await async_playwright().start()

        self.config = await load_config(self.session_id)
        log(f"Session: {self.session_id} ({self.config.get('email', '?')})")
        log(f"Project: {self.project_id}")
        log(f"Browser: {self.browser_type}")

        # Launch browser
        if self.browser_type == "chromium":
            self.browser = await self.pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage",
                       "--disable-blink-features=AutomationControlled"])
        else:
            self.browser = await self.pw.firefox.launch(headless=True)

        self.context = await self.browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

        # Load cookies
        cookies = await load_cookies(self.session_id)
        await self.context.add_cookies(cookies)
        log(f"Loaded {len(cookies)} cookies")

        # Open preview page
        self.page = await self.context.new_page()
        preview_url = f"https://{self.project_id}.lovableproject.com"
        log(f"Opening preview: {preview_url}")
        try:
            await self.page.goto(preview_url, timeout=30000, wait_until="commit")
        except Exception:
            pass
        await self.page.wait_for_timeout(5000)

        # Open chat page
        self.chat_page = await self.context.new_page()
        chat_url = f"https://lovable.dev/projects/{self.project_id}"
        log(f"Opening chat: {chat_url}")
        try:
            await self.chat_page.goto(chat_url, timeout=30000, wait_until="commit")
        except Exception:
            pass
        await self.chat_page.wait_for_timeout(3000)

        # Check if logged in on chat
        url = self.chat_page.url
        if "/login" in url:
            log("Not logged in — doing login...")
            ok = await do_login(
                self.chat_page,
                self.config["email"],
                self.config["password"],
                self.config.get("totp_secret"))
            if not ok:
                raise Exception("Login failed")
            # Reload preview after login
            try:
                await self.page.goto(preview_url, timeout=30000, wait_until="commit")
            except Exception:
                pass
            await self.page.wait_for_timeout(5000)

        # Restore localStorage + IndexedDB
        sdir = SESSIONS_DIR / f"session-{self.session_id}"
        ls_file = sdir / "localstorage.json"
        if ls_file.exists():
            try:
                with open(ls_file) as f:
                    ls_data = json.load(f)
                if "lovable.dev" not in self.page.url:
                    try:
                        await self.page.goto("https://lovable.dev", timeout=15000, wait_until="commit")
                    except Exception:
                        pass
                await self.page.evaluate(
                    "(data) => { for (const [k, v] of Object.entries(data)) { try { localStorage.setItem(k, v); } catch(e) {} } }",
                    ls_data)
                log(f"Restored {len(ls_data)} localStorage keys")
            except Exception as e:
                log(f"localStorage restore failed: {e}")

        log("Setup complete")

    async def inject_worker(self):
        """Inject the miner worker into the preview sandbox."""
        from miner_injector import inject_miner
        try:
            result = await inject_miner(
                self.page, self.chat_page,
                self.project_id, self.config,
                mode=self.mode, threads=self.threads,
                bridge_url=BRIDGE_URL)
            if result:
                self.worker_running = True
                log("Worker injected and running")
                return True
            else:
                log("Worker injection returned False")
                return False
        except Exception as e:
            log(f"Worker injection error: {e}")
            return False

    async def check_health(self):
        """Quick health check — is worker alive and preview healthy."""
        try:
            # Check preview page is still loading
            url = self.page.url
            if "/login" in url:
                log("  Preview redirected to login — session expired")
                return False

            # Check for doc bridge (worker alive)
            try:
                alive = await self.page.evaluate(
                    "() => typeof window.doc === 'function'")
                if alive:
                    log("  Worker alive (doc bridge OK)")
                    return True
                else:
                    log("  Worker dead (no doc bridge)")
                    return False
            except Exception:
                log("  Preview unreachable")
                return False
        except Exception as e:
            log(f"  Health check error: {e}")
            return False

    async def do_recovery(self):
        """Attempt to recover: refresh token, re-login if needed, re-inject worker."""
        self.recovery_count += 1
        log(f"RECOVERY ATTEMPT {self.recovery_count}/{MAX_RECOVERY_ATTEMPTS}")

        # Step 1: Try token refresh
        ok = await refresh_firebase_token(self.page)
        if ok:
            await save_trio(self.context, self.page, self.session_id)
            # Re-navigate to preview
            preview_url = f"https://{self.project_id}.lovableproject.com"
            try:
                await self.page.goto(preview_url, timeout=30000, wait_until="commit")
            except Exception:
                pass
            await self.page.wait_for_timeout(5000)
            # Re-inject
            if await self.inject_worker():
                self.recovery_count = 0
                return True

        # Step 2: Full re-login
        log("  Token refresh failed, doing full re-login...")
        ok = await do_login(
            self.chat_page,
            self.config["email"],
            self.config["password"],
            self.config.get("totp_secret"))
        if ok:
            await save_trio(self.context, self.chat_page, self.session_id)
            # Reload preview
            preview_url = f"https://{self.project_id}.lovableproject.com"
            try:
                await self.page.goto(preview_url, timeout=30000, wait_until="commit")
            except Exception:
                pass
            await self.page.wait_for_timeout(5000)
            # Re-inject
            if await self.inject_worker():
                self.recovery_count = 0
                return True

        # Step 3: Try chat page re-login
        log("  Retrying login via chat page...")
        chat_url = f"https://lovable.dev/projects/{self.project_id}"
        try:
            await self.chat_page.goto(chat_url, timeout=30000, wait_until="commit")
        except Exception:
            pass
        await self.chat_page.wait_for_timeout(3000)
        ok = await do_login(
            self.chat_page,
            self.config["email"],
            self.config["password"],
            self.config.get("totp_secret"))
        if ok:
            await save_trio(self.context, self.chat_page, self.session_id)
            # Reload preview
            preview_url = f"https://{self.project_id}.lovableproject.com"
            try:
                await self.page.goto(preview_url, timeout=30000, wait_until="commit")
            except Exception:
                pass
            await self.page.wait_for_timeout(5000)
            if await self.inject_worker():
                self.recovery_count = 0
                return True

        log(f"  Recovery failed (attempt {self.recovery_count})")
        return False

    async def run_forever(self):
        """Main loop: health checks + token refresh + auto-recovery."""
        await self.setup()

        # Initial injection
        if not await self.inject_worker():
            log("Initial injection failed — will retry in health loop")

        self.last_token_refresh = time.time()
        self.last_health_check = time.time()

        while self.running:
            try:
                now = time.time()

                # Token refresh every 40 min
                if now - self.last_token_refresh >= TOKEN_REFRESH_INTERVAL:
                    log("--- TOKEN REFRESH ---")
                    ok = await refresh_firebase_token(self.page)
                    if ok:
                        await save_trio(self.context, self.page, self.session_id)
                    self.last_token_refresh = now

                # Health check every 3 min
                if now - self.last_health_check >= HEALTH_INTERVAL:
                    log(f"--- HEALTH CHECK ---")
                    healthy = await self.check_health()
                    if not healthy:
                        # Try recovery with backoff
                        recovered = False
                        for attempt in range(MAX_RECOVERY_ATTEMPTS):
                            backoff = RECOVERY_BACKOFF[min(attempt, len(RECOVERY_BACKOFF)-1)]
                            log(f"  Waiting {backoff}s before recovery attempt {attempt+1}...")
                            await asyncio.sleep(backoff)
                            if await self.do_recovery():
                                recovered = True
                                break
                        if not recovered:
                            log("ALL RECOVERY ATTEMPTS FAILED — will keep retrying...")
                            # Don't die — keep trying with longer backoff
                            await asyncio.sleep(300)
                            # Reset browser state
                            try:
                                await self.browser.close()
                            except Exception:
                                pass
                            try:
                                self.browser = await self.pw.chromium.launch(
                                    headless=True,
                                    args=["--no-sandbox", "--disable-dev-shm-usage",
                                           "--disable-blink-features=AutomationControlled"])
                                self.context = await self.browser.new_context(
                                    viewport={"width": 1280, "height": 720})
                                cookies = await load_cookies(self.session_id)
                                await self.context.add_cookies(cookies)
                                self.page = await self.context.new_page()
                                self.chat_page = await self.context.new_page()
                                preview_url = f"https://{self.project_id}.lovableproject.com"
                                try:
                                    await self.page.goto(preview_url, timeout=30000, wait_until="commit")
                                except Exception:
                                    pass
                                chat_url = f"https://lovable.dev/projects/{self.project_id}"
                                try:
                                    await self.chat_page.goto(chat_url, timeout=30000, wait_until="commit")
                                except Exception:
                                    pass
                                await self.page.wait_for_timeout(5000)
                                if await self.inject_worker():
                                    self.recovery_count = 0
                                    log("Browser relaunch + re-inject successful")
                            except Exception as e:
                                log(f"Browser relaunch failed: {e}")
                    self.last_health_check = now

                # Sleep until next check
                next_check = min(
                    self.last_health_check + HEALTH_INTERVAL,
                    self.last_token_refresh + TOKEN_REFRESH_INTERVAL)
                sleep_time = max(10, next_check - time.time())
                await asyncio.sleep(sleep_time)

            except KeyboardInterrupt:
                log("Interrupted — shutting down")
                self.running = False
            except Exception as e:
                log(f"Main loop error: {e}")
                traceback.print_exc()
                await asyncio.sleep(30)

    async def cleanup(self):
        try:
            await save_trio(self.context, self.page, self.session_id)
        except Exception:
            pass
        try:
            await self.browser.close()
        except Exception:
            pass
        try:
            await self.pw.stop()
        except Exception:
            pass
        log("Daemon stopped")


async def main():
    parser = argparse.ArgumentParser(description="Autonomous Miner Daemon")
    parser.add_argument("--session", required=True, help="Session ID (e.g., session-2)")
    parser.add_argument("--project", required=True, help="Lovable project ID")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox"])
    parser.add_argument("--threads", type=int, default=64)
    parser.add_argument("--mode", default="full", choices=["full", "oneshot", "gh"])
    args = parser.parse_args()

    daemon = MinerDaemon(args.session, args.project, args.browser, args.threads, args.mode)
    try:
        await daemon.run_forever()
    finally:
        await daemon.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
