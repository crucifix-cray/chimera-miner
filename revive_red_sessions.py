#!/usr/bin/env python3
"""
Revive Red Sessions - Re-login flagged sessions and clear the red flag.

For each red session in the Mega DB:
  1. Load config (email + password, password == email)
  2. Open https://lovable.dev/login, fill email + password, submit
  3. Wait for dashboard (logged in)
  4. Overwrite the session's cookies.json with fresh cookies
  5. Set session status back to active (remove red flag) and sync to Mega

Usage:
  python3 revive_red_sessions.py                    # all red sessions
  python3 revive_red_sessions.py --session 6        # specific session
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
from mega_db import load_db, save_db

SESSIONS_DIR = Path(
    os.environ.get(
        "CHIMERA_SESSIONS_DIR",
        "/home/alan/Documents/automation-toolkit/scripts/sessions",
    )
)

LOGIN_URL = "https://lovable.dev/login"
DASHBOARD_MARKERS = ["/projects", "/dashboard"]


async def load_session_config(session_id: str):
    session_path = SESSIONS_DIR / session_id
    with open(session_path / "config.json") as f:
        return json.load(f)


async def save_fresh_cookies(context, session_id: str):
    cookies = await context.cookies()
    session_path = SESSIONS_DIR / session_id
    with open(session_path / "cookies.json", "w") as f:
        json.dump(cookies, f, indent=2)
    print(f"   ✅ Cookies overwritten ({len(cookies)} cookies)")


async def login_session(browser, config: dict) -> str:
    """Login to Lovable with email/password in a FRESH context.

    Returns: "ok" (logged in), "lost" (invalid credentials - account is dead), "failed" (other error)
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
        """Check if the login form shows an invalid-credentials error."""
        for selector in LOST_SELECTORS:
            try:
                el = await page.wait_for_selector(selector, timeout=2500)
                if el and await el.is_visible():
                    print(f"   ⚠️  INVALID CREDENTIALS error shown ({selector})")
                    return True
            except:
                continue
        return False

    try:
        print(f"   🌐 Opening {LOGIN_URL}")
        await page.goto(LOGIN_URL, timeout=60000)
        await page.wait_for_load_state("domcontentloaded", timeout=30000)
        await asyncio.sleep(4)

        # Already logged in?
        if any(m in page.url for m in DASHBOARD_MARKERS):
            print("   ✅ Already logged in")
            await save_fresh_cookies(context, config["session_id"])
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
            # Check if already logged in after email step (magic link / oauth)
            if any(m in page.url for m in DASHBOARD_MARKERS):
                print("   ✅ Logged in after email step")
                await save_fresh_cookies(context, config["session_id"])
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
                await save_fresh_cookies(context, config["session_id"])
                return "ok"

        print("   ❌ Login did not reach dashboard")
        return "failed"

    except Exception as e:
        print(f"   ❌ Login error: {e}")
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


async def main():
    parser = argparse.ArgumentParser(description="Revive red sessions")
    parser.add_argument("--session", type=str, default=None, help="Specific session ID (default: all red)")
    args = parser.parse_args()

    print("=" * 60)
    print("🚀 REVIVE RED SESSIONS")
    print("=" * 60)

    db = load_db()

    targets = []
    if args.session:
        session_id = args.session if args.session.startswith("session-") else f"session-{args.session}"
        s = db.get_session(session_id)
        if not s:
            print(f"❌ Session {session_id} not in database")
            return
        targets = [s]
    else:
        targets = [s for s in db.data["sessions"] if s.get("status") == "red"]

    if not targets:
        print("✅ No red sessions to revive")
        return

    print(f"🎯 Reviving {len(targets)} red session(s): {[t['id'] for t in targets]}")

    async with InvisiblePlaywright() as browser:
        for session in targets:
            session_id = session["id"]
            print(f"\n{'='*60}")
            print(f"🔄 Session {session_id} ({session.get('email')})")
            print(f"{'='*60}")

            config = await load_session_config(session_id)
            config["session_id"] = session_id
            email = config.get("email", "unknown")

            result = await login_session(browser, config)

            if result == "ok":
                db.update_session(session_id, status="active", flag_reason="")
                print(f"   ✅ Session {session_id} ({email}) REVIVED → active")
            elif result == "lost":
                db.update_session(session_id, status="truly_red", flag_reason="invalid credentials - account lost")
                print(f"   💀 Session {session_id} ({email}) marked TRULY RED (account lost)")
            else:
                print(f"   ❌ Session {session_id} ({email}) login failed, keeping red")

    save_db(db)
    print("\n🏁 Done! Red sessions revived, DB synced to Mega.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()