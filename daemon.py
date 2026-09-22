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

_default_sessions = Path("/app/work/scripts/sessions")
if not _default_sessions.is_dir():
    _default_sessions = Path(
        "/home/alan/Documents/repos/automation-toolkit/scripts/sessions")
SESSIONS_DIR = Path(os.environ.get("CHIMERA_SESSIONS_DIR", str(_default_sessions)))
BRIDGE_URL = "wss://chimera-bridge-production-0703.up.railway.app"

TOKEN_REFRESH_INTERVAL = 2400  # 40 min

# Script3 wake prompts only — NOT Build a debug terminal (that's script2).
WAKE_PROMPTS = ["say 'a'", "1+1?", "say 'x'", "2+2?", "echo ok"]


def ts():
    return time.strftime("%H:%M:%S", time.localtime())


def log(msg):
    print(f"[{ts()}] {msg}", flush=True)


# Revive is simple: refresh chat → wake cmd → wait → preview → inject → repeat
WAKE_ROUNDS = 15
WAKE_GOTO_MS = 45000
WAKE_SEL_MS = 10000
WAKE_AFTER_SEND_S = 12       # let sandbox spin after wake cmd
REVIVE_WALL_S = 420          # room for wake + wait + lovable + inject
REVIVE_LOVABLE_S = 180
FAIL_STREAK_RESTART = 3      # soft reconnect after this; hard kill only if CDP dead
RECONNECT_STREAK_HARD = 3    # N failed reconnects → kill Chrome entirely
# Preview cools to proxy-404 without human-like presence — poke both tabs often.
HEALTH_INTERVAL_S = 40
PRESENCE_KEYS = ("ArrowDown", "ArrowUp")  # Home/PageDown disrupt Lovable chat UI
PRESENCE_POKE_TIMEOUT_S = 10
# Every health tick also send a trivial chat prompt — keeps sandbox warm.
PRESENCE_PROMPT_AFTER_S = 3
PRESENCE_PROMPT_TIMEOUT_S = 20
# Every 2 min, reload chat before the presence prompt (clears upgrade modal / CDP sludge).
PRESENCE_REFRESH_EVERY_S = 120
# Don't full-revive on a single flaky nodoc — confirm dead first.
HEALTH_DEAD_CONFIRM = 2
HEALTH_DEAD_GAP_S = 12
SOFT_DEAD_DETAILS = ("nodoc", "worker-missing", "no-probe", "probe-error",
                     "doc-eval-error", "body-error", "probe-eval-error")
# Startup composer hunt: look → miss → wait → repeat; then kill+rerun (no 5min nap).
COMPOSER_TRIES = 15
COMPOSER_WAIT_S = 10
SHOT_DIR = Path(os.environ.get("CHIMERA_SHOT_DIR", "/app/work/shots"))
CDP_URL = os.environ.get("CHIMERA_CDP_URL", "http://127.0.0.1:9222")
CHROME_PROFILE = Path(os.environ.get(
    "CHIMERA_CHROME_PROFILE", "/tmp/chimera-chrome-profile"))
CHROME_BIN = os.environ.get("CHIMERA_CHROME_BIN", "")  # auto-detect if empty

CHAT_COMPOSER_SELECTORS = [
    'div[contenteditable="true"][role="textbox"]',
    '[data-testid="chat-composer-editor"] [role="textbox"]',
    '[data-testid="chat-composer-editor"]',
    'div.ProseMirror[contenteditable="true"]',
    '[role="textbox"][contenteditable="true"]',
    '[contenteditable="true"]',
    "textarea",
]


def kill_browser_orphans() -> None:
    """SIGKILL leftover Playwright Chromium trees, reap zombies, wipe temp profiles."""
    import glob
    import shutil
    import signal
    import subprocess

    killed = 0
    try:
        out = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True, timeout=10)
    except Exception as e:
        log(f"  Orphan scan fail: {e}")
        out = ""
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        pid_s, args = parts[0], parts[1]
        if "Xvfb" in args or "daemon.py" in args:
            continue
        # Only Playwright / chrome-for-testing trees — never host browsers
        if not (
            "ms-playwright" in args
            or "playwright_chromium" in args
            or "chrome-linux64/chrome" in args
            or "chrome_crashpad_handler" in args
        ):
            continue
        try:
            os.kill(int(pid_s), signal.SIGKILL)
            killed += 1
        except Exception:
            pass

    reaped = 0
    while True:
        try:
            wpid, _ = os.waitpid(-1, os.WNOHANG)
            if wpid <= 0:
                break
            reaped += 1
        except ChildProcessError:
            break
        except Exception:
            break

    for d in glob.glob("/tmp/playwright_chromiumdev_profile-*"):
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    if killed or reaped:
        log(f"  Killed browser orphans={killed} reaped_zombies={reaped}")


def cdp_http_alive(timeout: float = 2.0) -> bool:
    """True when Chrome remote-debugging HTTP is answering on CDP_URL."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{CDP_URL.rstrip('/')}/json/version",
                                    timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _find_chrome_bin() -> str:
    if CHROME_BIN and Path(CHROME_BIN).is_file():
        return CHROME_BIN
    import glob
    cands = sorted(glob.glob(
        "/root/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    if cands:
        return cands[-1]
    for p in ("/usr/bin/chromium", "/usr/bin/google-chrome",
              "/usr/bin/chromium-browser"):
        if Path(p).is_file():
            return p
    return ""


def spawn_chrome_cdp(headed: bool = True) -> bool:
    """Start Chromium with --remote-debugging-port if CDP is down. Returns True if up."""
    import subprocess
    if cdp_http_alive():
        return True
    bin_ = _find_chrome_bin()
    if not bin_:
        log("  spawn_chrome: no chrome binary found")
        return False
    CHROME_PROFILE.mkdir(parents=True, exist_ok=True)
    port = "9222"
    try:
        from urllib.parse import urlparse
        port = str(urlparse(CDP_URL).port or 9222)
    except Exception:
        pass
    args = [
        bin_,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={CHROME_PROFILE}",
        "--no-first-run", "--no-default-browser-check",
        "--disable-dev-shm-usage", "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu", "--disable-software-rasterizer",
        "--js-flags=--max-old-space-size=512",
    ]
    if not headed:
        args.append("--headless=new")
    try:
        env = os.environ.copy()
        if headed and not env.get("DISPLAY"):
            env["DISPLAY"] = ":99"
        subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            env=env,
        )
    except Exception as e:
        log(f"  spawn_chrome fail: {e}")
        return False
    for _ in range(25):
        time.sleep(0.4)
        if cdp_http_alive():
            log(f"  Chrome CDP up at {CDP_URL}")
            return True
    log("  spawn_chrome: CDP never came up")
    return False


def hard_kill_chrome() -> None:
    """Kill Playwright orphans AND our persistent chimera Chrome; wait until CDP is dead."""
    import signal
    import subprocess
    kill_browser_orphans()
    try:
        out = subprocess.check_output(["ps", "-eo", "pid=,args="], text=True, timeout=10)
    except Exception:
        out = ""
    killed = 0
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        pid_s, args = parts[0], parts[1]
        if "daemon.py" in args or "Xvfb" in args:
            continue
        hit = (
            "chimera-chrome-profile" in args
            or "remote-debugging-port=9222" in args
            or ("chrome" in args.lower() and "ms-playwright" in args)
            or "playwright_chromiumdev_profile" in args
        )
        if not hit:
            continue
        try:
            os.kill(int(pid_s), signal.SIGKILL)
            killed += 1
        except Exception:
            pass
    # Nuclear belt-and-suspenders
    for pat in (
        "remote-debugging-port=9222",
        "chimera-chrome-profile",
        "playwright_chromiumdev_profile",
        "ms-playwright/chromium",
    ):
        try:
            subprocess.run(
                ["pkill", "-9", "-f", pat],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except Exception:
            pass
    if killed:
        log(f"  Hard-killed chrome procs={killed}")
    for i in range(30):
        if not cdp_http_alive(timeout=0.4):
            log(f"  CDP port clear after hard kill ({i * 0.3:.1f}s)")
            return
        time.sleep(0.3)
    log("  WARNING: CDP still answering after hard kill — will spawn anyway")


async def connect_cdp_browser(pw):
    """Attach Playwright to existing Chrome over CDP."""
    browser = await pw.chromium.connect_over_cdp(CDP_URL)
    return browser


async def find_or_open_chat(browser, chat_url: str, project_id: str):
    """Reuse existing lovable.dev project tab if present; else open one."""
    context = browser.contexts[0] if browser.contexts else await browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    )
    chat_page = None
    for page in list(context.pages):
        try:
            u = page.url or ""
        except Exception:
            continue
        if f"lovable.dev/projects/{project_id}" in u and "/login" not in u:
            chat_page = page
            break
    if chat_page is None:
        # any lovable.dev project tab
        for page in list(context.pages):
            try:
                u = page.url or ""
            except Exception:
                continue
            if "lovable.dev/projects/" in u:
                chat_page = page
                break
    if chat_page is None:
        chat_page = await context.new_page()
        log(f"Opening chat: {chat_url}")
        try:
            await chat_page.goto(chat_url, timeout=30000, wait_until="commit")
        except Exception:
            pass
        await chat_page.wait_for_timeout(2000)
    else:
        log(f"  Reusing existing chat tab: {(chat_page.url or '')[:100]}")
        try:
            await chat_page.bring_to_front()
        except Exception:
            pass
    return context, chat_page


async def light_focus(page) -> None:
    """Bring tab forward + gentle mouse — no PageDown/End (scrolls composer away)."""
    if page is None:
        return
    try:
        if page.is_closed():
            return
    except Exception:
        return
    try:
        await asyncio.wait_for(page.bring_to_front(), timeout=3)
    except Exception:
        pass
    try:
        await asyncio.wait_for(page.mouse.move(200, 200), timeout=3)
        await asyncio.sleep(0.1)
        await asyncio.wait_for(page.mouse.move(400, 400, steps=4), timeout=3)
        await asyncio.wait_for(page.mouse.click(400, 40), timeout=3)
    except Exception:
        pass


async def find_chat_composer(page, tag: str = ""):
    """Find contenteditable fast. JS probe FIRST — click loops hang CDP on Railway.

    Returns (locator_or_None, cdp_hung: bool).
    cdp_hung only when JS *and* locator probes all hard-timeout (true wedge).
    """
    if page is None:
        return None, False
    tag_s = f" {tag}" if tag else ""
    js_timed_out = False

    # 1) Fast JS count (hard 8s) — cold SPA hydrate often exceeds 4s without true wedge
    try:
        n = await _page_eval(
            page,
            "() => document.querySelectorAll('[contenteditable=\"true\"]').length",
            timeout=8,
        )
        log(f"  Composer: JS contenteditable count={n}{tag_s}")
        if n and int(n) >= 1:
            loc = page.locator('[contenteditable="true"]').first
            try:
                await asyncio.wait_for(loc.click(timeout=2000), timeout=3)
            except Exception:
                pass
            return loc, False
    except asyncio.TimeoutError:
        js_timed_out = True
        log(f"  Composer: JS probe timeout{tag_s} — try locators before calling hung")
    except Exception as e:
        log(f"  Composer: JS probe fail ({type(e).__name__}){tag_s}")

    # 2) Light Ask Lovable click (short caps)
    for click_try in (
        lambda: page.get_by_placeholder("Ask Lovable", exact=False).first,
        lambda: page.locator('[data-testid="chat-composer-editor"]').first,
    ):
        try:
            loc = click_try()
            await asyncio.wait_for(loc.click(timeout=1500), timeout=2.5)
            await asyncio.sleep(0.3)
            log(f"  Composer: clicked Ask Lovable{tag_s}")
            break
        except Exception:
            continue

    locator_timeouts = 0
    for sel in CHAT_COMPOSER_SELECTORS[:4]:
        try:
            loc = page.locator(sel).first
            await asyncio.wait_for(
                loc.wait_for(state="visible", timeout=1500), timeout=2.5)
            try:
                await asyncio.wait_for(loc.click(timeout=1500), timeout=2.5)
            except Exception:
                pass
            log(f"  Composer: found via locator {sel[:40]}{tag_s}")
            return loc, False
        except asyncio.TimeoutError:
            locator_timeouts += 1
            continue
        except Exception:
            continue
    # True wedge: JS timed out AND every locator attempt also timed out
    if js_timed_out and locator_timeouts >= 2:
        log(f"  Composer: CDP likely hung{tag_s} (js+locator timeouts)")
        return None, True
    return None, False


async def _page_eval(page, js: str, timeout: float = 8.0):
    """page.evaluate with hard timeout — hung Chromium must not block forever."""
    return await asyncio.wait_for(page.evaluate(js), timeout=timeout)


async def send_wake_prompt(
    chat_page,
    chat_url: str | None = None,
    session_config: dict | None = None,
) -> bool:
    """Find composer → send trivial wake cmd → wait.

    Prefer no-reload when already on the project chat (reload → skeleton wedge).
    """
    import random as _rand

    try:
        await asyncio.wait_for(chat_page.bring_to_front(), timeout=5)
    except Exception:
        pass

    async def _type_and_send(chat_input, prompt: str) -> bool:
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
                'button[data-testid="chat-input-send"], '
                'button[aria-label*="Send" i]'
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

    # Fast path: already on project — do not reload
    try:
        cur0 = chat_page.url or ""
    except Exception:
        cur0 = ""
    on_project = bool(
        chat_url and chat_url.rstrip("/") in (cur0.split("?")[0] or ""))
    if on_project:
        chat_input, cdp_hung = await find_chat_composer(
            chat_page, tag="wake-fast")
        if cdp_hung:
            log("  Wake: CDP hung on fast path — HARD kill needed")
            return False
        if chat_input:
            return await _type_and_send(chat_input, _rand.choice(WAKE_PROMPTS))

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
        await light_focus(chat_page)
        await asyncio.sleep(COMPOSER_WAIT_S)  # wait then look again

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
                await asyncio.sleep(COMPOSER_WAIT_S)

        chat_input, cdp_hung = await find_chat_composer(
            chat_page, tag=f"wake-r{round_n}")
        if chat_input:
            log(f"  Wake: chat input found (round {round_n})")
            break
        if cdp_hung:
            log("  Wake: CDP hung — HARD kill needed (renderer wedged)")
            return False

        log(f"  Wake: no composer yet — refresh again")
        await asyncio.sleep(2)

    if not chat_input:
        log(f"  Wake: chat input not found after {WAKE_ROUNDS} refreshes")
        return False

    return await _type_and_send(chat_input, _rand.choice(WAKE_PROMPTS))


async def refresh_chat_for_presence(chat_page, chat_url: str | None = None) -> bool:
    """Reload chat before a presence prompt (every ~2 min). Soft-fail."""
    if chat_page is None:
        return False
    try:
        if chat_page.is_closed():
            return False
    except Exception:
        return False
    try:
        await asyncio.wait_for(chat_page.bring_to_front(), timeout=5)
    except Exception:
        pass
    # Dismiss upgrade / credits modal if it is blocking the composer
    for label in ("Cancel", "Not now", "Close", "Maybe later"):
        try:
            btn = chat_page.get_by_role("button", name=label, exact=False)
            n = await asyncio.wait_for(btn.count(), timeout=2)
            if n > 0 and await btn.first.is_visible(timeout=1000):
                await btn.first.click(timeout=2000)
                log(f"  Presence refresh: dismissed '{label}'")
                await asyncio.sleep(0.8)
                break
        except Exception:
            continue
    try:
        cur = ""
        try:
            cur = chat_page.url or ""
        except Exception:
            cur = ""
        log("  Presence refresh: reloading chat (2min tick)")
        if chat_url and chat_url.rstrip("/") in (cur.split("?")[0] or ""):
            await chat_page.reload(timeout=45000, wait_until="commit")
        elif chat_url:
            await chat_page.goto(chat_url, timeout=45000, wait_until="commit")
        else:
            await chat_page.reload(timeout=45000, wait_until="commit")
        await asyncio.sleep(4)
        await light_focus(chat_page)
        return True
    except Exception as e:
        log(f"  Presence refresh soft-fail: {type(e).__name__}")
        return False


async def send_presence_prompt(chat_page) -> bool:
    """Health-tick trivial chat prompt (say 'a' / 1+1? …). Soft-fail unless crash."""
    import random as _rand

    if chat_page is None:
        return False
    try:
        if chat_page.is_closed():
            return False
    except Exception:
        return False

    async def _do() -> bool:
        chat_input, cdp_hung = await find_chat_composer(
            chat_page, tag="presence")
        if cdp_hung:
            raise asyncio.TimeoutError("cdp hung on presence composer")
        if not chat_input:
            log("  Presence prompt: no composer — skip")
            return False
        prompt = _rand.choice(WAKE_PROMPTS)
        log(f"  Presence prompt: sending '{prompt}'")
        try:
            await chat_input.click(timeout=3000)
        except Exception:
            pass
        try:
            await chat_input.fill(prompt, timeout=5000)
        except Exception:
            try:
                await chat_page.keyboard.type(prompt, delay=20)
            except Exception as e:
                log(f"  Presence prompt type fail: {type(e).__name__}")
                return False
        await asyncio.sleep(0.25)
        try:
            send_btn = chat_page.locator(
                'button[data-testid="chat-input-send"], '
                'button[aria-label*="Send" i]'
            ).first
            if await send_btn.count() and await send_btn.is_visible(timeout=1500):
                await send_btn.click()
            else:
                await chat_page.keyboard.press("Enter")
        except Exception:
            try:
                await chat_page.keyboard.press("Enter")
            except Exception:
                pass
        log(f"  Presence prompt: sent — wait {PRESENCE_PROMPT_AFTER_S}s")
        await asyncio.sleep(PRESENCE_PROMPT_AFTER_S)
        return True

    try:
        return await asyncio.wait_for(_do(), timeout=PRESENCE_PROMPT_TIMEOUT_S)
    except asyncio.TimeoutError:
        log("  Presence prompt timeout (CDP?)")
        return False
    except Exception as e:
        if _is_crash_error(e):
            raise
        log(f"  Presence prompt soft-fail: {type(e).__name__}")
        return False


async def steal_preview_url_from_chat(chat_page) -> str | None:
    """Pull the live preview iframe URL from the Lovable chat UI.

    Bare https://{id}.lovableproject.com forces auth-bridge (often hangs on Railway).
    Chat Preview panel already has a sessioned iframe (id-preview / __lovable_sha).
    """
    try:
        await asyncio.wait_for(chat_page.bring_to_front(), timeout=5)
    except Exception:
        pass
    for label in ("Preview", "preview"):
        try:
            btn = chat_page.get_by_role("button", name=label, exact=False)
            n = await asyncio.wait_for(btn.count(), timeout=3)
            if n > 0:
                await btn.first.click(timeout=3000)
                await asyncio.sleep(1.5)
                log("  Steal: clicked Preview tab")
                break
        except Exception:
            continue
    await asyncio.sleep(2)

    urls = []
    try:
        for fr in chat_page.frames:
            try:
                u = fr.url or ""
            except Exception:
                continue
            if not u or u.startswith("about:"):
                continue
            ul = u.lower()
            if any(x in ul for x in (
                "lovableproject.com", "id-preview", "lovable.app",
                "webcontainer", "auth-bridge",
            )):
                urls.append(u)
    except Exception as e:
        log(f"  Steal frames fail: {type(e).__name__}: {e}")

    # Prefer lovableproject.com (Shell Sandbox) over id-preview cold mirrors.
    ranked = sorted(
        urls,
        key=lambda u: (
            0 if "auth-bridge" in u else 1,
            3 if "lovableproject.com" in u else (
                1 if ("__lovable_sha" in u or "id-preview" in u) else 0),
            len(u),
        ),
        reverse=True,
    )
    for u in ranked:
        if "auth-bridge" in u:
            continue
        log(f"  Stolen preview URL: {u[:140]}")
        return u
    if ranked:
        log(f"  Steal only auth-bridge: {ranked[0][:140]}")
        return ranked[0]
    log("  Steal: no preview iframe URL in chat")
    return None


async def ensure_preview_shell_panel(chat_page) -> None:
    """Click Preview + Shell so the lovableproject iframe remounts."""
    if chat_page is None:
        return

    async def _do():
        try:
            await asyncio.wait_for(chat_page.bring_to_front(), timeout=5)
        except Exception:
            pass
        for label in ("Preview", "preview"):
            try:
                btn = chat_page.get_by_role("button", name=label, exact=False)
                n = await asyncio.wait_for(btn.count(), timeout=3)
                if n > 0:
                    await btn.first.click(timeout=3000)
                    await asyncio.sleep(1.2)
                    log("  Panel: clicked Preview")
                    break
            except Exception:
                continue
        for label in ("Shell", "shell", "Terminal", "terminal"):
            try:
                btn = chat_page.get_by_role("button", name=label, exact=False)
                n = await asyncio.wait_for(btn.count(), timeout=2)
                if n > 0:
                    await btn.first.click(timeout=2500)
                    await asyncio.sleep(1.0)
                    log(f"  Panel: clicked {label}")
                    break
            except Exception:
                continue

    try:
        await asyncio.wait_for(_do(), timeout=25)
    except Exception as e:
        log(f"  Panel open soft-fail: {type(e).__name__}")


def _sandbox_frame_score(frame) -> int:
    """Rank chat Preview frames for window.doc probes (skip chat chrome)."""
    try:
        u = (frame.url or "").lower()
    except Exception:
        return -1
    if "auth-bridge" in u:
        return -1
    if "lovable.dev" in u and "lovableproject" not in u:
        return -1
    try:
        is_main = frame.parent_frame is None
    except Exception:
        is_main = False
    if not u or u.startswith("about:"):
        return 8 if not is_main else -1
    score = 0
    if "lovableproject.com" in u:
        score += 100
    if "webcontainer" in u or "stackblitz" in u:
        score += 40
    if "id-preview" in u or ("lovable.app" in u and "preview" in u):
        score += 20
    if "localhost:" in u or "127.0.0.1:" in u:
        score += 10
    return score


async def _probe_frame_doc_pwd(fr, timeout: float = 6.0):
    """Hard-bounded doc+pwd probe. Never let one frame wedge the wait loop."""
    try:
        return await asyncio.wait_for(
            fr.evaluate(
                """async () => {
                if (window.doc && typeof window.doc !== 'function') {
                    try { delete window.doc; } catch (e) { window.doc = undefined; }
                    return { ok: false, err: 'cleared-fake' };
                }
                if (!window.doc || typeof window.doc !== 'function') {
                    if (window.lovable) return { ok: false, err: 'lovable-obj-no-doc' };
                    return { ok: false, err: 'no-doc' };
                }
                try {
                    if (window.doc.connect) {
                        try { await window.doc.connect(); } catch (e) {}
                    }
                    const r = await window.doc('pwd');
                    return { ok: true, r: r };
                } catch (e) {
                    return { ok: false, err: String(e && e.message || e).slice(0, 120) };
                }
            }"""
            ),
            timeout=timeout,
        )
    except Exception as e:
        return {"ok": False, "err": type(e).__name__}


async def wait_for_chat_preview_sandbox(
    chat_page, timeout_seconds: int = 120
) -> bool:
    """Wait until a chat Preview frame exposes window.doc (Shell Sandbox).

    Prefers lovableproject.com; also accepts id-preview / nested shell frames.
    Probes only top-ranked frames with short timeouts so CDP wedges cannot
    stall past timeout_seconds (seen as 'Waiting...' forever on Railway).
    """
    log(f"Waiting for chat Preview sandbox/doc (max {timeout_seconds}s)...")
    await ensure_preview_shell_panel(chat_page)

    start = asyncio.get_running_loop().time()
    last_note = ""
    last_tick = 0.0
    last_remount = 0.0
    while True:
        elapsed = asyncio.get_running_loop().time() - start
        if elapsed > timeout_seconds:
            log(f"  Chat Preview sandbox timeout after {timeout_seconds}s"
                + (f" ({last_note})" if last_note else ""))
            return False

        # Remount Preview/Shell periodically — doc often appears only after remount
        if elapsed - last_remount >= 28:
            last_remount = elapsed
            try:
                await asyncio.wait_for(
                    ensure_preview_shell_panel(chat_page), timeout=20)
            except Exception as e:
                last_note = f"remount:{type(e).__name__}"

        try:
            frames = list(chat_page.frames)
        except Exception:
            frames = []

        ranked = []
        for fr in frames:
            sc = _sandbox_frame_score(fr)
            if sc > 0:
                ranked.append((sc, fr))
        ranked.sort(key=lambda x: -x[0])
        # Cap probes per pass — many frames × long evaluate = apparent forever hang
        candidates = ranked[:5]

        if elapsed - last_tick >= 15:
            last_tick = elapsed
            urls = []
            for sc, fr in candidates:
                try:
                    urls.append(f"{sc}:{(fr.url or '')[:55]}")
                except Exception:
                    urls.append(f"{sc}:?")
            log(f"  Sandbox wait {int(elapsed)}s "
                f"frames={len(frames)} probe={len(candidates)} "
                f"[{', '.join(urls) or 'none'}] "
                f"last={last_note or '-'}")

        soft = None  # non-lovableproject frame with working pwd
        for sc, fr in candidates:
            try:
                u = fr.url or ""
            except Exception:
                u = ""
            ul = u.lower()
            probe = await _probe_frame_doc_pwd(fr, timeout=6.0)
            if not isinstance(probe, dict):
                continue
            if not probe.get("ok"):
                err = str(probe.get("err", "?"))[:50]
                if sc >= 20:
                    last_note = f"{u[:70]}:{err}"
                continue
            if "lovableproject.com" in ul:
                log(f"  Chat Preview sandbox ready (lovableproject+pwd): {u[:120]}")
                return True
            soft = soft or u
        if soft:
            log(f"  Chat Preview sandbox ready (pwd): {soft[:120]}")
            return True
        await asyncio.sleep(4)


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
            or "id-preview" in cur_url
            or "lovable.app" in cur_url
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
            # Bare lovableproject hang — escape sooner than local (Railway stalls)
            if elapsed > 35:
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
                await asyncio.sleep(5)
            else:
                await asyncio.sleep(5)
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
    Recover shell/worker.
    Iframe mode: soft re-inject first (NO chat reload) — reload wedges CDP on Railway.
    Separate preview tab: wake → goto → inject.
    """
    from miner_injector import inject_miner

    same_page = preview_page is chat_page
    if same_page:
        log("  Revive: iframe soft path (no reload) — wait sandbox + reinject")
        try:
            await asyncio.wait_for(
                steal_preview_url_from_chat(chat_page), timeout=30)
        except Exception as e:
            log(f"  Revive steal fail: {type(e).__name__}")
        ready = await wait_for_chat_preview_sandbox(
            chat_page, timeout_seconds=90)
        if ready:
            log("  Revive: soft inject into chat Preview iframe")
            try:
                ok = await asyncio.wait_for(
                    inject_miner(chat_page, bridge_url, threads), timeout=200)
            except Exception as e:
                log(f"  Revive soft inject fail: {type(e).__name__}")
                ok = False
            if ok:
                log("  Revive inject: OK (soft)")
                return True
        log("  Revive: soft path failed — wake + retry (may reload)")
        woke = await send_wake_prompt(
            chat_page, chat_url=chat_url, session_config=session_config)
        if not woke:
            log("  Revive: wake failed — browser restart needed")
            return False
        ready = await wait_for_chat_preview_sandbox(
            chat_page, timeout_seconds=min(REVIVE_LOVABLE_S, 120))
        if not ready:
            log("  Revive: lovable/doc never ready (iframe)")
            return False
        log("  Revive: injecting worker into chat Preview iframe")
        ok = await inject_miner(chat_page, bridge_url, threads)
        log(f"  Revive inject: {'OK' if ok else 'FAILED'}")
        return bool(ok)

    log("  Revive: refresh chat → wake → wait → preview → inject")
    woke = await send_wake_prompt(
        chat_page, chat_url=chat_url, session_config=session_config)
    if not woke:
        log("  Revive: wake failed — retry next cycle")
        return False

    # Prefer stolen sessioned iframe URL over bare lovableproject
    try:
        stolen = await asyncio.wait_for(
            steal_preview_url_from_chat(chat_page), timeout=45)
        if stolen:
            preview_url = stolen
    except Exception as e:
        log(f"  Revive steal fail: {type(e).__name__}")

    # Preview tab: hard re-nav then wait for window.doc
    if preview_url:
        try:
            log(f"  Revive: goto preview")
            await preview_page.goto(preview_url, timeout=45000, wait_until="commit")
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
    Checks main frame then preview iframes (chat-embedded Preview panel).
    Soft-retries once on transient nodoc — iframe remounts briefly after presence.
    """
    cur_url = ""
    try:
        cur_url = preview_page.url or ""
    except Exception as e:
        return False, f"url-error:{e}"
    if "auth-bridge" in cur_url and "lovable.dev/auth-bridge" in cur_url:
        pass
    if "/login" in cur_url and "lovable.dev" in cur_url:
        return False, "login"

    async def _probe_frame(frame, label: str):
        try:
            fu = frame.url or ""
        except Exception:
            fu = ""
        # Doc first — body text eval hangs CDP on heavy Lovable chat DOM
        try:
            has_doc = await asyncio.wait_for(
                frame.evaluate(
                    "() => !!(window.doc && typeof window.doc === 'function')"),
                timeout=6,
            )
        except Exception as e:
            return False, f"doc-eval-error:{type(e).__name__}"
        if not has_doc:
            # Cheap proxy-404 check only when no doc
            try:
                body = await asyncio.wait_for(
                    frame.evaluate(
                        "() => (document.body && document.body.innerText || '').slice(0, 400)"),
                    timeout=5,
                )
                bl = (body or "").lower()
                if ("proxy error" in bl or "lovable proxy error" in bl) and "404" in bl:
                    return False, "proxy-404"
            except Exception:
                pass
            return False, "nodoc"
        try:
            probe = await asyncio.wait_for(
                frame.evaluate(
                    """async () => {
                    try {
                        const r = await window.doc("ps -A -o args | grep -c '[s]ysoptd'");
                        return r && r.stdout !== undefined ? r.stdout.trim() : 'no-probe';
                    } catch(e) { return 'probe-error'; }
                }"""),
                timeout=12,
            )
        except Exception as e:
            return False, f"probe-eval-error:{type(e).__name__}"
        if str(probe).isdigit() and int(probe) > 0:
            return True, f"{probe}@{label}"
        return False, f"worker-missing:{probe}"

    async def _once() -> tuple[bool, str]:
        frames = []
        try:
            frames = list(preview_page.frames)
        except Exception:
            frames = []
        ranked = []
        for fr in frames:
            try:
                u = (fr.url or "").lower()
            except Exception:
                u = ""
            score = 0
            if "lovableproject.com" in u:
                score = 3
            elif any(x in u for x in ("id-preview", "webcontainer", "lovable.app")):
                score = 2
            elif fr == preview_page.main_frame:
                score = 1
            if score:
                ranked.append((score, fr))
        ranked.sort(key=lambda x: -x[0])

        last = "nodoc"
        for score, fr in ranked:
            try:
                lab = (fr.url or "")[:60]
            except Exception:
                lab = "frame"
            ok, detail = await _probe_frame(fr, lab)
            if ok:
                return True, detail
            last = detail
            if detail.startswith("proxy-404"):
                return False, detail
        return False, last

    ok, detail = await _once()
    if ok:
        return ok, detail
    soft = any(
        detail == p or detail.startswith(p + ":") or detail.startswith(p)
        for p in SOFT_DEAD_DETAILS)
    if soft:
        await asyncio.sleep(HEALTH_DEAD_GAP_S)
        ok2, detail2 = await _once()
        if ok2:
            log(f"  Soft re-probe recovered: {detail2}")
            return ok2, detail2
        return False, detail2
    return False, detail


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
    if os.environ.get("CHIMERA_SKIP_IDB", "") == "1":
        log("  Skipping IndexedDB save (CHIMERA_SKIP_IDB=1)")
        return
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


async def detect_auth_wall(page) -> bool:
    """True if Lovable shows login / private-project access wall."""
    if page is None:
        return False
    try:
        cur = (page.url or "").lower()
    except Exception:
        cur = ""
    if "/login" in cur or "/auth" in cur:
        return True
    try:
        body = await _page_eval(
            page,
            "() => (document.body && document.body.innerText || '').slice(0, 600)",
            timeout=8,
        )
    except Exception:
        return False
    bl = (body or "").lower()
    if "you don't have access" in bl or "this project is private" in bl:
        return True
    if ("log in" in bl or "sign in" in bl) and (
        "password" in bl or "request access" in bl or "permissions" in bl
    ):
        return True
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


def _is_crash_error(exc: BaseException | str) -> bool:
    """True when Playwright/browser is dead and only a full relaunch helps."""
    s = str(exc).lower()
    needles = (
        "target closed",
        "target page, context or browser has been closed",
        "browser has been closed",
        "browser closed",
        "connection closed",
        "page closed",
        "context closed",
        "protocol error",
        "chromium has crashed",
        "browser disconnected",
        "websocket",
        "execution context was destroyed",
    )
    return any(n in s for n in needles)


async def _browser_alive(browser, chat_page, preview_page) -> bool:
    try:
        if browser is None or not browser.is_connected():
            return False
    except Exception:
        return False
    try:
        if chat_page is not None and chat_page.is_closed():
            return False
    except Exception:
        return False
    try:
        if preview_page is not None and preview_page.is_closed():
            return False
    except Exception:
        return False
    return True


async def capture_debug(chat_page, preview_page, tag: str) -> None:
    """Playwright page shots + Xvfb root shot so we can see headed :99 state."""
    try:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"  Shot dir fail: {e}")
        return
    stamp = time.strftime("%H%M%S")
    pages = [(chat_page, "chat")]
    if preview_page is not None and preview_page is not chat_page:
        pages.append((preview_page, "preview"))
    for page, label in pages:
        if page is None:
            continue
        try:
            if page.is_closed():
                continue
        except Exception:
            continue
        path = SHOT_DIR / f"{stamp}_{tag}_{label}.png"
        try:
            await asyncio.wait_for(
                page.screenshot(path=str(path), full_page=False, timeout=5000),
                timeout=8,
            )
            log(f"  Shot {label}: {path.name}")
        except Exception as e:
            log(f"  Shot {label} fail: {type(e).__name__}")

    display = os.environ.get("DISPLAY") or ""
    if display:
        xvfb_path = SHOT_DIR / f"{stamp}_{tag}_xvfb.png"
        try:
            proc = await asyncio.create_subprocess_exec(
                "import", "-display", display, "-window", "root", str(xvfb_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=12)
            if proc.returncode == 0 and xvfb_path.exists():
                log(f"  Shot xvfb: {xvfb_path.name}")
            else:
                log(f"  Shot xvfb fail rc={proc.returncode}")
        except Exception as e:
            log(f"  Shot xvfb fail: {type(e).__name__}: {e}")


async def keep_pages_warm(chat_page, preview_page) -> None:
    """Human-like presence: scroll chat, hover/wheel preview iframe, light keys.

    Avoids top-chrome clicks and Home/PageDown (those remount Preview → nodoc).
    Iframe mode: one rich poke on the chat page covering both surfaces.
    """
    import random as _r

    async def _human_chat(page, label: str) -> None:
        if page is None:
            return
        try:
            if page.is_closed():
                return
        except Exception:
            return

        async def _do():
            try:
                await page.bring_to_front()
            except Exception:
                pass
            # JS: scroll chat transcript + hover/mousemove on preview iframe
            try:
                await asyncio.wait_for(page.evaluate("""() => {
                    const pick = (sel) => document.querySelector(sel);
                    // scroll main chat column if present
                    const scrolls = [
                        ...document.querySelectorAll(
                          '[data-radix-scroll-area-viewport], .overflow-y-auto, [class*="overflow-y"]')
                    ].filter(el => el.scrollHeight > el.clientHeight + 40);
                    if (scrolls.length) {
                        const el = scrolls[0];
                        const delta = (Math.random() > 0.5 ? 1 : -1) * (80 + Math.random() * 160);
                        el.scrollTop = Math.max(0, Math.min(el.scrollHeight, el.scrollTop + delta));
                    }
                    const ifr = pick('#live-preview-panel')
                        || [...document.querySelectorAll('iframe')].find(i =>
                             /lovableproject|id-preview|lovable\\.app/i.test(i.src || i.id || ''));
                    if (ifr) {
                        const r = ifr.getBoundingClientRect();
                        if (r.width > 20 && r.height > 20) {
                            const x = r.left + r.width * (0.3 + Math.random() * 0.4);
                            const y = r.top + r.height * (0.3 + Math.random() * 0.4);
                            for (const typ of ['mouseover', 'mousemove', 'mouseenter']) {
                                ifr.dispatchEvent(new MouseEvent(typ, {
                                    bubbles: true, clientX: x, clientY: y, view: window
                                }));
                            }
                            // also nudge parent so Lovable sees activity
                            document.elementFromPoint(x, y)?.dispatchEvent(
                                new MouseEvent('mousemove', {
                                    bubbles: true, clientX: x, clientY: y, view: window
                                }));
                        }
                    }
                    // visibility / focus signals
                    window.dispatchEvent(new Event('focus'));
                    document.dispatchEvent(new Event('visibilitychange'));
                    return true;
                }"""), timeout=6)
            except Exception:
                pass
            vp = page.viewport_size or {"width": 1280, "height": 720}
            w, h = int(vp.get("width", 1280)), int(vp.get("height", 720))
            # Mouse path over mid chat (left) then preview (right) — no top bar
            cx = _r.randint(int(w * 0.15), int(w * 0.35))
            cy = _r.randint(int(h * 0.35), int(h * 0.75))
            px = _r.randint(int(w * 0.55), int(w * 0.88))
            py = _r.randint(int(h * 0.35), int(h * 0.75))
            await page.mouse.move(cx, cy, steps=_r.randint(3, 6))
            await asyncio.sleep(_r.uniform(0.08, 0.2))
            await page.mouse.wheel(0, _r.choice([-120, 120]))
            await asyncio.sleep(_r.uniform(0.08, 0.2))
            await page.mouse.move(px, py, steps=_r.randint(3, 7))
            await asyncio.sleep(0.08)
            await page.mouse.wheel(0, _r.choice([-100, 100]))
            await page.mouse.click(px, py)
            key = _r.choice(PRESENCE_KEYS)
            await page.keyboard.press(key)
            if _r.random() < 0.25:
                try:
                    await asyncio.wait_for(page.evaluate("""() => {
                        const el = document.querySelector(
                          '[contenteditable="true"], textarea');
                        if (el) el.focus();
                    }"""), timeout=2)
                    await asyncio.sleep(0.2)
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
            log(f"  Presence poke ok ({label}: scroll/hover/wheel/{key})")

        try:
            await asyncio.wait_for(_do(), timeout=PRESENCE_POKE_TIMEOUT_S)
        except asyncio.TimeoutError:
            log(f"  Presence poke timeout ({label} >{PRESENCE_POKE_TIMEOUT_S}s)")
        except Exception as e:
            if _is_crash_error(e):
                raise
            log(f"  Presence poke soft-fail ({label}): {type(e).__name__}")

    same = preview_page is chat_page
    await _human_chat(chat_page, "chat+preview" if same else "chat")
    if not same and preview_page is not None:
        # dedicated preview tab — lighter mouse + wheel only
        async def _poke_preview():
            try:
                await preview_page.bring_to_front()
            except Exception:
                pass
            vp = preview_page.viewport_size or {"width": 1280, "height": 720}
            w, h = int(vp.get("width", 1280)), int(vp.get("height", 720))
            x = _r.randint(100, max(120, w - 100))
            y = _r.randint(100, max(120, h - 100))
            await preview_page.mouse.move(x, y, steps=6)
            await preview_page.mouse.wheel(0, _r.choice([-150, 150]))
            await preview_page.mouse.click(x, y)
            await preview_page.keyboard.press(_r.choice(PRESENCE_KEYS))
            log("  Presence poke ok (preview: move/wheel/click)")
        try:
            await asyncio.wait_for(_poke_preview(), timeout=PRESENCE_POKE_TIMEOUT_S)
        except asyncio.TimeoutError:
            log(f"  Presence poke timeout (preview >{PRESENCE_POKE_TIMEOUT_S}s)")
        except Exception as e:
            if _is_crash_error(e):
                raise
            log(f"  Presence poke soft-fail (preview): {type(e).__name__}")


async def run_daemon(session_id, project_id, browser_type, threads, mode, headed=False):
    from playwright.async_api import async_playwright
    from miner_injector import inject_miner

    config = load_config_sync(session_id)
    log(f"Session: {session_id} ({config.get('email', '?')})")
    log(f"Project: {project_id}")
    log(f"Browser: {browser_type} headed={headed}")
    log("Forever mode: crash / script error → revive → continue (never exit)")

    preview_url = f"https://{project_id}.lovableproject.com"
    chat_url = f"https://lovable.dev/projects/{project_id}"

    cycle = 0
    reconnect_streak = 0
    force_hard_kill = False
    while True:  # outer forever — prefer CDP reconnect; hard-kill only when needed
        cycle += 1
        log(f"=== Browser cycle #{cycle} (reconnect_streak={reconnect_streak}) ===")
        pw = None
        browser = None
        attached = False
        exit_mode = "reconnect"  # health sets kill when CDP dead
        try:
            # Hard kill clears wedged Chrome before relaunch
            if force_hard_kill or reconnect_streak >= RECONNECT_STREAK_HARD:
                log("  Hard-killing Chrome (reconnect exhausted or forced)")
                hard_kill_chrome()
                force_hard_kill = False
                reconnect_streak = 0

            pw = await async_playwright().start()

            # Prefer Playwright launch (stable on Railway). CDP attach only for
            # soft reconnect when Chrome was left up intentionally.
            want_attach = (
                reconnect_streak > 0
                and cdp_http_alive()
                and not force_hard_kill
            )
            if browser_type == "chromium":
                if want_attach:
                    try:
                        browser = await connect_cdp_browser(pw)
                        attached = True
                        log(f"  Soft-reattached via CDP {CDP_URL}")
                    except Exception as e:
                        log(f"  CDP attach fail ({e}) — fresh launch")
                        want_attach = False
                if not want_attach:
                    if cdp_http_alive():
                        hard_kill_chrome()
                    _args = ["--no-sandbox", "--disable-dev-shm-usage",
                             "--disable-blink-features=AutomationControlled",
                             "--js-flags=--max-old-space-size=512",
                             "--disable-gpu", "--disable-software-rasterizer",
                             "--remote-debugging-port=9222"]
                    browser = await pw.chromium.launch(
                        headless=not headed, args=_args)
                    attached = False
                    log("  Launched Chromium via Playwright")
                if attached:
                    context, chat_page = await find_or_open_chat(
                        browser, chat_url, project_id)
                else:
                    context = await browser.new_context(
                        viewport={"width": 1280, "height": 720},
                        user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
                    chat_page = await context.new_page()
                    log(f"Opening chat: {chat_url}")
                    try:
                        await chat_page.goto(chat_url, timeout=30000, wait_until="commit")
                    except Exception:
                        pass
                    await chat_page.wait_for_timeout(3000)
            else:
                browser = await pw.firefox.launch(headless=not headed)
                attached = False
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
                chat_page = await context.new_page()
                log(f"Opening chat: {chat_url}")
                try:
                    await chat_page.goto(chat_url, timeout=30000, wait_until="commit")
                except Exception:
                    pass
                await chat_page.wait_for_timeout(3000)

            # Load cookies into context (no-op if profile already has them)
            try:
                cookies = load_cookies_sync(session_id)
                await context.add_cookies(cookies)
                log(f"Loaded {len(cookies)} cookies")
            except Exception as e:
                log(f"  Cookie load soft-fail: {e}")

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
                    raise RuntimeError("login-failed-retry")
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
            if idb_file.exists() and os.environ.get("CHIMERA_SKIP_IDB", "") != "1":
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
            elif idb_file.exists():
                log("Skipping IndexedDB restore (CHIMERA_SKIP_IDB=1)")

            # After LS restore: wait for hydrate. Avoid reload here — it often
            # wedges CDP on Railway while Lovable SPA is still compiling.
            await asyncio.sleep(12)

            # Cookie banner + auth wall (SKIP_IDB often leaves us logged-out)
            try:
                ok_btn = chat_page.get_by_role("button", name="OK", exact=True)
                if await ok_btn.count():
                    await ok_btn.first.click(timeout=2000)
                    log("  Dismissed cookie OK")
            except Exception:
                pass
            if await detect_auth_wall(chat_page):
                log("  Auth wall after restore — re-login")
                logged = await do_login(
                    chat_page,
                    config.get("email", ""),
                    config.get("password", ""),
                    config.get("totp_secret"),
                )
                if not logged:
                    log("  Re-login failed — HARD kill cycle")
                    force_hard_kill = True
                    raise RuntimeError("cycle-restart")
                try:
                    await chat_page.goto(
                        chat_url, timeout=45000, wait_until="commit")
                except Exception:
                    pass
                await asyncio.sleep(15)
                if await detect_auth_wall(chat_page):
                    log("  Still auth-walled after login — HARD kill cycle")
                    force_hard_kill = True
                    raise RuntimeError("cycle-restart")
                log("  Auth wall cleared — continuing")

            # Extra settle after cookie/LS/auth before any CDP frame walks
            await asyncio.sleep(8)
            # Do NOT probe preview frames before composer — cold shell_worker_status
            # wedges CDP while the SPA is still hydrating (Xvfb looks fine, evaluate hangs).
            preview_page = chat_page
            injected = False
            alive0, det0 = False, "deferred"

            import random as _rand
            chat_input = None
            cdp_hung_streak = 0
            if not injected:
              for round_n in range(1, COMPOSER_TRIES + 1):
                if await detect_auth_wall(chat_page):
                    log(f"  Auth wall mid composer hunt (r{round_n}) — re-login")
                    logged = await do_login(
                        chat_page,
                        config.get("email", ""),
                        config.get("password", ""),
                        config.get("totp_secret"),
                    )
                    if logged:
                        try:
                            await chat_page.goto(
                                chat_url, timeout=45000, wait_until="commit")
                        except Exception:
                            pass
                        await asyncio.sleep(8)
                    else:
                        force_hard_kill = True
                        raise RuntimeError("cycle-restart")
                await light_focus(chat_page)
                chat_input, cdp_hung = await find_chat_composer(
                    chat_page, tag=f"start-r{round_n}")
                if chat_input:
                    log(f"Chat input found (round {round_n}/{COMPOSER_TRIES})")
                    break
                if cdp_hung:
                    cdp_hung_streak += 1
                    log(f"CDP slow on composer (round {round_n}, "
                        f"streak={cdp_hung_streak}/3) — retry not hard-kill yet")
                    if cdp_hung_streak >= 3:
                        log("CDP hung 3x on composer hunt — HARD kill")
                        force_hard_kill = True
                        raise RuntimeError("cycle-restart")
                else:
                    cdp_hung_streak = 0
                log(f"Chat input missing (round {round_n}/{COMPOSER_TRIES}) — wait {COMPOSER_WAIT_S}s (no reload)")
                if round_n in (1, 5, 10, COMPOSER_TRIES):
                    try:
                        await asyncio.wait_for(
                            capture_debug(chat_page, None, f"no-composer-r{round_n}"),
                            timeout=15)
                    except Exception:
                        log("  Shot skip (CDP slow)")
                # Prefer waiting over reload — reload → skeleton / CDP wedge
                await light_focus(chat_page)
                await asyncio.sleep(COMPOSER_WAIT_S)

              if not chat_input:
                log("Chat input not found — CDP reconnect (keep Chrome if up)")
                raise RuntimeError(
                    "cdp-reconnect" if cdp_http_alive() else "cycle-restart")

              prompt = _rand.choice(WAKE_PROMPTS)
              log(f"Sending wake prompt: '{prompt}'")
              try:
                  await chat_input.click(timeout=5000)
              except Exception:
                  pass
              try:
                  await chat_input.fill(prompt, timeout=10000)
              except Exception:
                  await chat_page.keyboard.type(prompt, delay=25)
              await asyncio.sleep(0.3)
              await chat_page.keyboard.press("Enter")
              log("Wake prompt sent!")
              log(f"  Post-wake spin {WAKE_AFTER_SEND_S}s for Shell Sandbox...")
              await asyncio.sleep(WAKE_AFTER_SEND_S)

              # --- Step 4: Inject into chat Preview lovableproject iframe (1 tab)
              preview_page = chat_page
              injected = False
              try:
                  await ensure_preview_shell_panel(chat_page)
                  stolen0 = await asyncio.wait_for(
                      steal_preview_url_from_chat(chat_page), timeout=30)
                  if stolen0 and "lovableproject.com" in stolen0:
                      preview_url = stolen0
              except Exception as e:
                  log(f"  Preview tab click/steal soft-fail: {type(e).__name__}")

              sandbox_in_chat = await wait_for_chat_preview_sandbox(
                  chat_page, timeout_seconds=150)
              if not sandbox_in_chat:
                  for wake_i in range(1, 3):
                      log(f"  Sandbox missing — presence prompt {wake_i}/2 "
                          f"(no reload) + wait")
                      try:
                          await asyncio.wait_for(
                              send_presence_prompt(chat_page), timeout=40)
                      except Exception as e:
                          log(f"  Soft presence skip: {type(e).__name__}")
                      await ensure_preview_shell_panel(chat_page)
                      sandbox_in_chat = await wait_for_chat_preview_sandbox(
                          chat_page, timeout_seconds=90)
                      if sandbox_in_chat:
                          break

              if sandbox_in_chat:
                  for inj_try in range(1, 3):
                      log(f"Injecting worker via chat Preview iframe (try {inj_try}/2)...")
                      await ensure_preview_shell_panel(chat_page)
                      try:
                          injected = bool(await asyncio.wait_for(
                              inject_miner(chat_page, BRIDGE_URL, threads),
                              timeout=200))
                      except Exception as e:
                          log(f"  Chat-frame inject fail: {type(e).__name__}: {e}")
                          injected = False
                      if injected:
                          break
                      if inj_try < 2:
                          try:
                              await asyncio.wait_for(
                                  send_presence_prompt(chat_page), timeout=40)
                          except Exception as e:
                              log(f"  Retry presence skip: {type(e).__name__}")
                          await wait_for_chat_preview_sandbox(
                              chat_page, timeout_seconds=60)
              else:
                  log("  No real window.doc — skip inject (avoid fake-doc / auth-bridge)")

              if not injected:
                  # Last-resort: stolen sessioned preview URL only (never bare host)
                  stolen = None
                  try:
                      await ensure_preview_shell_panel(chat_page)
                      stolen = await asyncio.wait_for(
                          steal_preview_url_from_chat(chat_page), timeout=45)
                  except Exception as e:
                      log(f"  Steal preview failed: {type(e).__name__}: {e}")
                  use_url = stolen
                  if not use_url or "auth-bridge" in use_url:
                      log("  No safe stolen preview URL — health loop will revive")
                  else:
                      preview_url = use_url
                      preview_page = await context.new_page()
                      log(f"Opening preview tab (fallback): {use_url[:140]}")
                      try:
                          await preview_page.goto(
                              use_url, timeout=45000, wait_until="commit")
                      except Exception as e:
                          log(f"  Preview goto error: {type(e).__name__}")
                      await preview_page.wait_for_timeout(2000)
                      sandbox_ready = await wait_for_lovable_console(
                          preview_page, timeout_seconds=120)
                      if not sandbox_ready:
                          log("Lovable console never ready — second wake + wait...")
                          await send_wake_prompt(
                              chat_page, chat_url=chat_url, session_config=config)
                          try:
                              stolen2 = await steal_preview_url_from_chat(chat_page)
                              if stolen2 and "auth-bridge" not in stolen2:
                                  use_url = stolen2
                                  preview_url = stolen2
                          except Exception:
                              pass
                          try:
                              await preview_page.goto(
                                  use_url, timeout=45000, wait_until="commit")
                          except Exception:
                              pass
                          sandbox_ready = await wait_for_lovable_console(
                              preview_page, timeout_seconds=120)
                      if sandbox_ready:
                          log("Injecting worker on preview tab...")
                          try:
                              injected = bool(await inject_miner(
                                  preview_page, BRIDGE_URL, threads))
                          except Exception as e:
                              log(f"Inject crashed: {e}")
                              injected = False
                      else:
                          log("Sandbox never ready on fallback tab — continue to health")

            if injected:
                log("Worker injected!" if not alive0 else "Worker already running (reconnect)")
            else:
                log("Worker injection returned False — health loop will retry")

            # Save state from chat origin (Firebase LS/IDB live on lovable.dev,
            # not the preview sandbox — saving from preview wipes the trio).
            try:
                await save_trio(context, chat_page, session_id)
            except Exception as e:
                log(f"save_trio error (continuing): {e}")

            if mode != "full":
                log(f"Mode={mode} — inject done, exiting (no health loop)")
                await browser.close()
                await pw.stop()
                return

            # Full mode: forever health — shell/worker dead → revive; crash → relaunch
            log("Starting health check loop (full mode)...")
            last_refresh = time.time()
            last_presence_reload = 0.0  # force refresh on first 2min-eligible tick
            page_lock = asyncio.Lock()  # serialize revive vs token refresh

            async def daemon_health_loop():
                """On shell/worker death: soft confirm → revive; prefer CDP reconnect over kill."""
                nonlocal exit_mode, reconnect_streak, force_hard_kill, last_presence_reload
                iteration = 0
                fail_streak = 0
                soft_dead = 0
                while True:
                    iteration += 1
                    log(f"Health check #{iteration}...")
                    next_wait = HEALTH_INTERVAL_S

                    # Browser/page gone → reconnect if CDP still up
                    if not await _browser_alive(browser, chat_page, preview_page):
                        exit_mode = "reconnect" if cdp_http_alive() else "kill"
                        log(f"  Browser/page closed — {exit_mode}")
                        return

                    # Keep chat+preview warm every cycle (idle → proxy 404 cool-off)
                    try:
                        await keep_pages_warm(chat_page, preview_page)
                    except Exception as e_warm:
                        if _is_crash_error(e_warm) or not await _browser_alive(
                                browser, chat_page, preview_page):
                            exit_mode = "reconnect" if cdp_http_alive() else "kill"
                            log(f"  Browser dead on presence poke — {exit_mode}")
                            return

                    # Trivial chat prompt every ~40s; every 2min reload chat first
                    if not page_lock.locked():
                        try:
                            now_pr = time.time()
                            if now_pr - last_presence_reload >= PRESENCE_REFRESH_EVERY_S:
                                await refresh_chat_for_presence(
                                    chat_page, chat_url=chat_url)
                                last_presence_reload = now_pr
                            await send_presence_prompt(chat_page)
                        except Exception as e_pp:
                            if _is_crash_error(e_pp) or not await _browser_alive(
                                    browser, chat_page, preview_page):
                                exit_mode = "reconnect" if cdp_http_alive() else "kill"
                                log(f"  Browser dead on presence prompt — {exit_mode}")
                                return
                            log(f"  Presence prompt skip: {type(e_pp).__name__}")

                    # Shots every other check — less CDP load on Railway
                    if iteration == 1 or iteration % 2 == 0:
                        await capture_debug(
                            chat_page, preview_page, f"h{iteration}")

                    try:
                        alive, detail = await asyncio.wait_for(
                            shell_worker_status(preview_page), timeout=45)
                        if alive:
                            fail_streak = 0
                            soft_dead = 0
                            reconnect_streak = 0
                            log(f"  Worker alive (probe: {detail})")
                            log("  Preview healthy")
                        else:
                            soft_dead += 1
                            log(f"  Shell/worker soft-dead ({detail}) "
                                f"confirm {soft_dead}/{HEALTH_DEAD_CONFIRM}")
                            if soft_dead < HEALTH_DEAD_CONFIRM:
                                next_wait = HEALTH_DEAD_GAP_S
                                await asyncio.sleep(next_wait)
                                continue
                            soft_dead = 0
                            log(f"  Shell/worker dead confirmed ({detail}) — revive")
                            await capture_debug(
                                chat_page, preview_page,
                                f"dead-{detail.replace('/', '-')[:40]}")
                            try:
                                if page_lock.locked():
                                    log("  waiting for page_lock (token refresh?)...")
                                async with page_lock:
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
                                    try:
                                        await save_trio(context, chat_page, session_id)
                                    except Exception:
                                        pass
                                    log("  Revive OK")
                                else:
                                    fail_streak += 1
                                    log(f"  Revive failed (streak={fail_streak}) — retry sooner")
                                    next_wait = 30
                                    if fail_streak >= FAIL_STREAK_RESTART:
                                        exit_mode = (
                                            "reconnect" if cdp_http_alive() else "kill")
                                        log(f"  Revive failed {FAIL_STREAK_RESTART}x — {exit_mode}")
                                        return
                            except asyncio.TimeoutError:
                                fail_streak += 1
                                log(f"  Revive timed out {REVIVE_WALL_S}s (streak={fail_streak})")
                                next_wait = 30
                                if fail_streak >= FAIL_STREAK_RESTART:
                                    exit_mode = (
                                        "reconnect" if cdp_http_alive() else "kill")
                                    log(f"  Revive timeout x{FAIL_STREAK_RESTART} — {exit_mode}")
                                    return
                            except Exception as e2:
                                fail_streak += 1
                                log(f"  Revive error: {e2} (streak={fail_streak})")
                                if _is_crash_error(e2) or not await _browser_alive(
                                        browser, chat_page, preview_page):
                                    exit_mode = (
                                        "reconnect" if cdp_http_alive() else "kill")
                                    log(f"  Crash during revive — {exit_mode}")
                                    return
                                next_wait = 30
                                if fail_streak >= FAIL_STREAK_RESTART:
                                    exit_mode = (
                                        "reconnect" if cdp_http_alive() else "kill")
                                    return

                    except asyncio.TimeoutError:
                        fail_streak += 1
                        log(f"  Health probe timed out 45s (streak={fail_streak})")
                        next_wait = 30
                        if fail_streak >= FAIL_STREAK_RESTART:
                            # HTTP :9222 can still answer while renderer is wedged
                            exit_mode = "kill"
                            force_hard_kill = True
                            log(f"  Probe dead {FAIL_STREAK_RESTART}x — hard kill (likely CDP wedge)")
                            return
                    except Exception as e:
                        log(f"  Health check error: {e}")
                        if _is_crash_error(e) or not await _browser_alive(
                                browser, chat_page, preview_page):
                            log("  Crash in health check — restarting browser")
                            return
                        next_wait = 30
                        fail_streak += 1
                        if fail_streak >= FAIL_STREAK_RESTART:
                            exit_mode = "reconnect" if cdp_http_alive() else "kill"
                            log(f"  Health errors {FAIL_STREAK_RESTART}x — {exit_mode}")
                            return

                    log(f"  Next check in {next_wait}s...")
                    await asyncio.sleep(next_wait)

            health_task = asyncio.create_task(daemon_health_loop())

            # Token refresh — never overlap with revive (same chat page)
            while not health_task.done():
                await asyncio.sleep(60)
                if not await _browser_alive(browser, chat_page, preview_page):
                    exit_mode = "reconnect" if cdp_http_alive() else "kill"
                    log(f"Browser died during token loop — {exit_mode}")
                    break
                now = time.time()
                if now - last_refresh >= TOKEN_REFRESH_INTERVAL:
                    if page_lock.locked():
                        log("--- TOKEN REFRESH skipped (revive in progress) ---")
                        continue
                    log("--- TOKEN REFRESH ---")
                    try:
                        async with page_lock:
                            tok_ok = await refresh_firebase_token(chat_page)
                            if tok_ok:
                                await save_trio(context, chat_page, session_id)
                    except Exception as e:
                        log(f"Token refresh error: {e}")
                        if _is_crash_error(e):
                            exit_mode = "reconnect" if cdp_http_alive() else "kill"
                            break
                    last_refresh = now

            # Drain health task if still running
            if not health_task.done():
                health_task.cancel()
                try:
                    await health_task
                except Exception:
                    pass

            # Soft CDP reconnect only when we attached (Chrome survives disconnect).
            # Playwright-launched Chrome dies with browser.close/pw.stop — hard cycle.
            if exit_mode != "kill" and attached and cdp_http_alive():
                log("Health cycle ended — CDP reconnect (Chrome stays up)...")
                raise RuntimeError("cdp-reconnect")
            log("Health cycle ended — hard Chrome restart...")
            raise RuntimeError("cycle-restart")

        except Exception as e:
            msg = str(e)
            do_hard_kill = False
            if msg == "login-failed-retry":
                wait_s = 300
                do_hard_kill = True
            elif msg == "sandbox-never-ready":
                wait_s = 120
                do_hard_kill = True
            elif msg == "cdp-reconnect":
                wait_s = 3
                reconnect_streak += 1
                log(f"  CDP reconnect streak={reconnect_streak}/{RECONNECT_STREAK_HARD}")
                if reconnect_streak >= RECONNECT_STREAK_HARD:
                    do_hard_kill = True
                    force_hard_kill = True
                    wait_s = 5
            elif msg == "cycle-restart":
                wait_s = 5
                do_hard_kill = True
                force_hard_kill = True
                reconnect_streak = 0
            else:
                log(f"Daemon error (will revive): {e}")
                traceback.print_exc()
                wait_s = 15
                # Prefer reconnect if Chrome CDP still answers
                do_hard_kill = not cdp_http_alive()
                if not do_hard_kill:
                    reconnect_streak += 1
                    msg = "cdp-reconnect"
            try:
                # CDP attach: close() disconnects without killing Chrome
                # Launched browser: close() kills it — only call on hard kill
                if browser is not None:
                    if do_hard_kill or not attached:
                        await browser.close()
                    else:
                        # Disconnect Playwright from CDP session only
                        try:
                            await browser.close()
                        except Exception:
                            pass
            except Exception:
                pass
            if do_hard_kill:
                hard_kill_chrome()
            log(f"Cleaning up — next cycle in {wait_s}s "
                f"({'HARD KILL' if do_hard_kill else 'CDP reconnect'})...")
            await asyncio.sleep(wait_s)
        finally:
            try:
                if pw is not None:
                    await pw.stop()
            except Exception:
                pass
            # Never auto-kill here — hard path already did; reconnect must keep Chrome


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

    # Even if run_daemon returns or asyncio/Playwright blows up — keep going
    # in full mode. Node EPIPE / driver death must not leave the cell idle.
    while True:
        try:
            asyncio.run(run_daemon(
                args.session, args.project, args.browser, args.threads,
                args.mode, headed=headed))
            if args.mode != "full":
                break
            log("run_daemon returned unexpectedly — hard-kill + restart in 10s")
            try:
                hard_kill_chrome()
            except Exception:
                pass
            time.sleep(10)
        except KeyboardInterrupt:
            log("Interrupted")
            break
        except BaseException as e:
            # Catch BaseException so SystemExit from driver death still restarts
            if isinstance(e, KeyboardInterrupt):
                log("Interrupted")
                break
            log(f"Fatal outer error (hard-kill + restart in 10s): "
                f"{type(e).__name__}: {e}")
            traceback.print_exc()
            try:
                hard_kill_chrome()
            except Exception:
                pass
            if args.mode != "full":
                raise
            time.sleep(10)


if __name__ == "__main__":
    main()
