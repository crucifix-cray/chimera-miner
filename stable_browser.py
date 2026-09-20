#!/usr/bin/env python3
"""
Stable browser launcher for Lovable automation on containers/sandboxes.

PROBLEM IT SOLVES:
- InvisiblePlaywright Firefox dies after ~3 min on Railway cells
  (protocol pipe breaks: "Browser.newPage: no response in 30s").
- Tor/proxy exit IPs get Lovable's "We hit a snag" error page.
- Cookies alone expire in ~1h (Firebase token lives in IndexedDB).

SOLUTION (proven 2026-09-20 on cell-16):
- Standard Playwright Chromium, headless, --no-sandbox --disable-dev-shm-usage
- Direct connection (CHIMERA_NO_PROXY=1 skips Tor/WARP auto-detect)
- Full session state: cookies.json + localstorage.json + indexeddb.json
  (IndexedDB holds Firebase stsTokenManager with refresh token)
- Silent Firebase token refresh via securetoken.googleapis.com (no re-login)

USAGE (any sandbox/cell — copy this file + session dir, no other deps):
    from stable_browser import launch_stable_browser, save_full_state, load_full_state

    async with async_playwright() as p:
        browser, context, page = await launch_stable_browser(
            p, session_dir="/app/work/scripts/sessions/session-2")
        await page.goto("https://lovable.dev/dashboard")
        ...
        await save_full_state(context, page, session_dir)  # before exit

STANDALONE (screenshot / probe any Lovable URL with a saved session):
    python3 stable_browser.py --session-dir scripts/sessions/session-2 \\
        --url https://lovable.dev/projects/<id> --shot /tmp/out.png
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

LOVABLE_ORIGIN = "https://lovable.dev"


async def launch_stable_browser(pw, session_dir, proxy=None, viewport=None):
    """Launch Chromium + restore full session state. Returns (browser, context, page).

    Args:
        pw: started async_playwright() instance
        session_dir: Path to session-N/ dir (cookies.json + localstorage.json + indexeddb.json)
        proxy: optional {"server": "socks5://..."} — default None (DIRECT, avoids flagged Tor IPs)
        viewport: optional {"width":1280,"height":720}
    """
    session_dir = Path(session_dir)
    with open(session_dir / "cookies.json") as f:
        cookies = json.load(f)

    kwargs = dict(headless=True, args=[
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
    ])
    if proxy:
        kwargs["proxy"] = proxy
    browser = await pw.chromium.launch(**kwargs)
    ctx_kwargs = {}
    if viewport:
        ctx_kwargs["viewport"] = viewport
    context = await browser.new_context(**ctx_kwargs)
    await context.add_cookies(cookies)
    page = await context.new_page()
    await load_full_state(context, page, session_dir)

    # Silent Firebase refresh so the 1h access token doesn't kill us mid-run
    try:
        await refresh_firebase_token(page)
    except Exception as e:
        print(f"   ⚠️  Firebase refresh skipped: {e}", file=sys.stderr)
    return browser, context, page


async def save_full_state(context, page, session_dir):
    """Save cookies + localStorage + IndexedDB (Firebase refresh token)."""
    session_dir = Path(session_dir)
    cookies = await context.cookies()
    with open(session_dir / "cookies.json", "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"   ✅ Saved {len(cookies)} cookies")

    # localStorage — must run on a non-CSP page; caller ensures domain visit first.
    # On lovable.dev itself, CSP blocks evaluate(); save from dashboard load instead.
    try:
        ls_data = await page.evaluate("""() => {
            const out = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                out[k] = localStorage.getItem(k);
            }
            return out;
        }""")
        with open(session_dir / "localstorage.json", "w") as f:
            json.dump(ls_data, f, indent=2)
        print(f"   ✅ Saved localStorage ({len(ls_data)} keys)")
    except Exception as e:
        print(f"   ⚠️  localStorage save skipped (CSP?): {str(e)[:100]}")

    try:
        idb_data = await page.evaluate("""async () => {
            return new Promise((resolve) => {
                try {
                    const req = indexedDB.open('firebaseLocalStorageDb');
                    req.onsuccess = () => {
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
                    };
                    req.onerror = () => resolve([]);
                } catch(e) { resolve([]); }
            });
        }""")
        with open(session_dir / "indexeddb.json", "w") as f:
            json.dump(idb_data, f, indent=2)
        has_refresh = any(
            r.get("value", {}).get("stsTokenManager", {}).get("refreshToken")
            for r in idb_data if isinstance(r.get("value"), dict)
        )
        print(f"   ✅ Saved IndexedDB ({len(idb_data)} records, refresh_token={'YES' if has_refresh else 'MISSING'})")
    except Exception as e:
        print(f"   ⚠️  IndexedDB save skipped (CSP?): {str(e)[:100]}")


async def load_full_state(context, page, session_dir, origin=LOVABLE_ORIGIN):
    """Restore localStorage + IndexedDB. Visits origin first (storage needs a domain)."""
    session_dir = Path(session_dir)
    ls_file = session_dir / "localstorage.json"
    if ls_file.exists():
        try:
            with open(ls_file) as f:
                ls_data = json.load(f)
            if "lovable.dev" not in (page.url or ""):
                await page.goto(origin, timeout=30000, wait_until="domcontentloaded")
            await page.evaluate(
                "(data) => { for (const [k, v] of Object.entries(data))"
                " { try { localStorage.setItem(k, v); } catch(e) {} } }",
                ls_data)
            print(f"   ✅ Restored localStorage ({len(ls_data)} keys)")
        except Exception as e:
            print(f"   ⚠️  localStorage restore skipped (CSP?): {str(e)[:100]}")
    idb_file = session_dir / "indexeddb.json"
    if idb_file.exists():
        try:
            with open(idb_file) as f:
                idb_data = json.load(f)
            if idb_data:
                if "lovable.dev" not in (page.url or ""):
                    await page.goto(origin, timeout=30000, wait_until="domcontentloaded")
                restored = await page.evaluate("""(records) => {
                    return new Promise((resolve) => {
                        try {
                            const delReq = indexedDB.deleteDatabase('firebaseLocalStorageDb');
                            delReq.onsuccess = delReq.onerror = delReq.onblocked = () => {
                                const openReq = indexedDB.open('firebaseLocalStorageDb');
                                openReq.onupgradeneeded = () => {
                                    openReq.result.createObjectStore('firebaseLocalStorage', {keyPath: 'fkey'});
                                };
                                openReq.onsuccess = () => {
                                    const db = openReq.result;
                                    const tx = db.transaction('firebaseLocalStorage', 'readwrite');
                                    const store = tx.objectStore('firebaseLocalStorage');
                                    let done = 0;
                                    if (!records.length) { resolve(0); return; }
                                    records.forEach(r => {
                                        try {
                                            const putReq = store.put({fkey: r.key, value: r.value});
                                            putReq.onsuccess = putReq.onerror = () => { if (++done === records.length) resolve(done); };
                                        } catch(e) { if (++done === records.length) resolve(done); }
                                    });
                                };
                                openReq.onerror = () => resolve(-1);
                            };
                        } catch(e) { resolve(-1); }
                    });
                }""", idb_data)
                print(f"   ✅ Restored IndexedDB ({restored} records)")
        except Exception as e:
            print(f"   ⚠️  IndexedDB restore skipped (CSP?): {str(e)[:100]}")


async def refresh_firebase_token(page):
    """Mint new Firebase access token via stored refresh token (no re-login).
    Returns True if fresh/refreshed, False otherwise."""
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
                                const exp = v.stsTokenManager.expirationTime || 0;
                                if (exp > Date.now() + 60000) { resolve({status: 'fresh', exp}); return; }
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
                                    } else { resolve({status: 'refresh_failed'}); }
                                } catch(e) { resolve({status: 'refresh_error'}); }
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
    print(f"   {'✅' if status in ('fresh', 'refreshed') else '⚠️'} Firebase token: {status}")
    return status in ("fresh", "refreshed")


async def _standalone(args):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, context, page = await launch_stable_browser(p, args.session_dir)
        await page.goto(args.url, timeout=60000)
        await page.wait_for_timeout(10000)
        n = await page.locator('div[contenteditable="true"][role="textbox"]').count()
        print(f"URL: {page.url}")
        print(f"chat_inputs: {n}")
        if args.shot:
            await page.screenshot(path=args.shot)
            print(f"shot: {args.shot}")
        if args.save:
            await save_full_state(context, page, args.session_dir)
        await browser.close()


def main():
    ap = argparse.ArgumentParser(description="Stable Chromium + full session state for Lovable")
    ap.add_argument("--session-dir", required=True, help="Path to session-N/ dir")
    ap.add_argument("--url", default="https://lovable.dev/dashboard")
    ap.add_argument("--shot", default=None, help="Save screenshot to path")
    ap.add_argument("--save", action="store_true", help="Re-save full state before exit")
    args = ap.parse_args()
    asyncio.run(_standalone(args))


if __name__ == "__main__":
    main()
