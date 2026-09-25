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

# Idle-typing phrases: typed into the composer but NEVER submitted.
# Unfinished dev thoughts — keydown/input activity with zero credit burn.
IDLE_TYPE_PHRASES = [
    "hmm the header…",
    "let me check the mobile view",
    "what if we ",
    "actually maybe ",
    "need to fix the spacing on ",
    "does this work on ",
    "wait, why is that ",
    "let me think… ",
]


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
# Consecutive failed health ticks before we give up on the current tab and open
# a fresh tab in the SAME browser (browser is never killed for soft issues).
FAIL_STREAK_RESTART = 6
RECONNECT_STREAK_HARD = 3    # legacy, unused for launched browsers
# Browser relaunch is last resort: only if the process died, or this many fresh
# tabs in a row never got past startup (renderer shared + wedged).
TAB_FAILS_BEFORE_BROWSER = 4
# Under CRITICAL mem: in-place revive miss/timeout this many times → hard-kill
# + relaunch (do NOT cap fail_streak forever — that left cells 13/35 worker-dead).
CRIT_REVIVE_BOUNCE = 3
# Headed Xvfb geometry — must match lean_sup Xvfb -screen and Chrome --window-size.
# 1024x576 collapsed Lovable Preview (blank canvas); 1600x900 fits chat+preview.
VIEW_W = int(os.environ.get("CHIMERA_VIEW_W", "1600"))
VIEW_H = int(os.environ.get("CHIMERA_VIEW_H", "900"))
# Blank white Preview (/term:no-doc): soft-reload chat every N forever-rounds,
# then hard-kill + relaunch browser so we do not sit forever on a dead shell.
BLANK_PREVIEW_RELOAD_ROUNDS = int(os.environ.get("CHIMERA_BLANK_RELOAD_ROUNDS", "6"))
BLANK_PREVIEW_HARD_ROUNDS = int(os.environ.get("CHIMERA_BLANK_HARD_ROUNDS", "12"))
# Preview cools to proxy-404 without human-like presence — poke both tabs often.
HEALTH_INTERVAL_S = 40
HEALTH_INTERVAL_MAX_S = 60  # randomize next tick in [40, 60]
PRESENCE_KEYS = ("ArrowDown", "ArrowUp")  # Home/PageDown disrupt Lovable chat UI
PRESENCE_POKE_TIMEOUT_S = 22
# Every health tick also send a trivial chat prompt — keeps sandbox warm.
PRESENCE_PROMPT_AFTER_S = 3
PRESENCE_PROMPT_TIMEOUT_S = 28
# Track last cursor so moves are continuous (humans don't teleport).
_HUMAN_MOUSE = {"x": VIEW_W * 0.45, "y": VIEW_H * 0.45}
# Don't full-revive on a single flaky nodoc — confirm dead first.
HEALTH_DEAD_CONFIRM = 2
HEALTH_DEAD_GAP_S = 12
SOFT_DEAD_DETAILS = ("nodoc", "worker-missing", "no-probe", "probe-error",
                     "doc-eval-error", "body-error", "probe-eval-error",
                     "proxy-404")
POPUP_DISMISS_LABELS = (
    "Cancel", "Not now", "Close", "Maybe later", "No thanks",
    "Dismiss", "Got it", "Continue", "Skip", "Later",
    # Cookie consent (blocks Preview iframe mount on some projects)
    "OK", "Accept", "Accept all", "I agree",
)
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
    ] + [a for a in _chromium_lean_args()
         if not a.startswith("--remote-debugging-port")]
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
        viewport={"width": VIEW_W, "height": VIEW_H},
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
        await asyncio.sleep(2)
    else:
        log(f"  Reusing existing chat tab: {(chat_page.url or '')[:100]}")
        try:
            await chat_page.bring_to_front()
        except Exception:
            pass
    return context, chat_page


async def light_focus(page) -> None:
    """Bring tab forward + gentle mouse — no PageDown/End (scrolls composer away)."""
    await ensure_page_focused(page)


async def install_focus_spoof(context) -> None:
    """Xvfb windows often look unfocused/hidden to the page — spoof visibility.

    Without this, Lovable / Chrome throttle timers & iframes on Railway headed
    Xvfb while local :99 can still look 'active' enough for Shell to mount.
    """
    if context is None:
        return
    try:
        await context.add_init_script(
            """
            (() => {
              try {
                Object.defineProperty(document, 'hidden', {
                  configurable: true, get: () => false
                });
                Object.defineProperty(document, 'visibilityState', {
                  configurable: true, get: () => 'visible'
                });
                document.hasFocus = () => true;
                window.addEventListener('blur', (e) => {
                  e.stopImmediatePropagation();
                  setTimeout(() => window.focus(), 0);
                }, true);
              } catch (e) {}
            })();
            """
        )
        log("  Focus spoof installed (document.hidden=false / hasFocus=true)")
    except Exception as e:
        log(f"  Focus spoof skip: {type(e).__name__}")


async def safe_goto(page, url: str, timeout_s: float = 18.0) -> bool:
    """Navigate without hanging forever when Playwright's goto wedges.

    Railway: Playwright can block the *entire* asyncio loop inside goto so
    asyncio.wait timeouts never fire. A daemon thread hard-kills Chrome after
    timeout_s — that unblocks the driver and lets forever-mode continue.
    """
    if page is None:
        return False
    try:
        if page.is_closed():
            return False
    except Exception:
        return False

    import threading

    target = url.split("?")[0].rstrip("/")
    stop = threading.Event()

    def _watchdog():
        if stop.wait(timeout_s + 2):
            return
        log("  safe_goto: thread-watchdog HARD KILL chrome")
        try:
            hard_kill_chrome()
        except Exception:
            pass

    threading.Thread(target=_watchdog, name="goto-wd", daemon=True).start()
    log(f"  safe_goto: navigating ({timeout_s:.0f}s watchdog)…")
    try:
        await page.goto(
            url,
            timeout=int(timeout_s * 1000),
            wait_until="commit",
        )
        stop.set()
        log("  safe_goto: commit ok")
        return True
    except Exception as e:
        stop.set()
        log(f"  safe_goto: {type(e).__name__}: {e}")
        try:
            cur = (page.url or "").split("?")[0].rstrip("/")
            if target and target in cur and not page.is_closed():
                log("  safe_goto: URL already live after err — ok")
                return True
        except Exception:
            pass
        return False


def cgroup_mem_gb() -> float:
    """Return cgroup memory.max in GB, or 0 if unknown."""
    try:
        with open("/sys/fs/cgroup/memory.max") as f:
            raw = f.read().strip()
        if raw == "max":
            return 99.0
        return int(raw) / 1_000_000_000
    except Exception:
        try:
            with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
                return int(f.read().strip()) / 1_000_000_000
        except Exception:
            return 0.0


def cgroup_mem_used_frac() -> float:
    """Fraction of cgroup memory used (0..1), or 0 if unknown."""
    try:
        with open("/sys/fs/cgroup/memory.current") as f:
            cur = int(f.read().strip())
        with open("/sys/fs/cgroup/memory.max") as f:
            raw = f.read().strip()
        if raw == "max":
            return 0.0
        mx = int(raw)
        if mx <= 0:
            return 0.0
        return min(1.0, cur / mx)
    except Exception:
        try:
            with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
                cur = int(f.read().strip())
            with open("/sys/fs/cgroup/memory/memory.limit_in_bytes") as f:
                mx = int(f.read().strip())
            if mx <= 0 or mx > (1 << 60):
                return 0.0
            return min(1.0, cur / mx)
        except Exception:
            return 0.0


def reap_zombies_only() -> int:
    """waitpid(-1, WNOHANG) only — never SIGKILL live Chrome."""
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
    if reaped:
        log(f"  Reaped zombies={reaped}")
    return reaped


def mem_pressure_tier() -> str:
    """ok | careful | critical — babysit load before Aw Snap on 1GB."""
    frac = cgroup_mem_used_frac()
    if frac >= 0.94:
        return "critical"
    if frac >= 0.88:
        return "careful"
    return "ok"


def reclaim_if_pressure(tag: str = "", *, allow_hard_kill: bool = True) -> bool:
    """Reap zombies. Hard-kill only at absolute cgroup ceiling (≥99.5%).

    Healthy Lovable+Chrome on 1GB sits at 90–97%. Killing there caused
    needless relaunch loops. Prefer mem_pressure_tier babysitting instead.

    Headed Xvfb + Worker on 1GB steady-state sits at ~100% (cell-16/13 proof:
    health-1 hard-kill right after "Worker injected!" → inject→kill loop).
    Never hard-kill for ceiling alone when FORCE_HEADED/DISPLAY is set —
    Aw Snap / page-dead paths still relaunch.
    """
    reap_zombies_only()
    frac = cgroup_mem_used_frac()
    if frac < 0.995:
        return False
    prefix = f"  {tag}: " if tag else "  "
    headed = (
        os.environ.get("CHIMERA_FORCE_HEADED", "") == "1"
        or bool((os.environ.get("DISPLAY") or "").strip())
    )
    if not allow_hard_kill or headed:
        why = "deferred" if not allow_hard_kill else "headed/DISPLAY"
        log(f"{prefix}Cgroup ceiling {frac:.0%} — skip hard-kill ({why}; babysit)")
        return False
    log(f"{prefix}Cgroup ceiling {frac:.0%} — hard-kill Chrome + reap zombies")
    hard_kill_chrome()
    return True


async def page_is_aw_snap(page) -> bool:
    """True when Chromium shows Aw, Snap / crashed renderer (OOM on 1GB cells)."""
    if page is None:
        return False
    try:
        if page.is_closed():
            return True
    except Exception:
        return True
    title = ""
    try:
        title = await asyncio.wait_for(page.title(), timeout=3)
    except Exception:
        title = ""
    tl = (title or "").lower()
    if "aw, snap" in tl or "sad tab" in tl:
        return True
    # Don't treat blank/evaluate-fail as crash — SPA hydrate is slow on Railway.
    # But Target crashed / closed IS a crash.
    try:
        body = await asyncio.wait_for(
            page.evaluate(
                "() => (document.body && document.body.innerText || '').slice(0, 240)"
            ),
            timeout=4,
        )
    except Exception as e:
        if _is_crash_error(e):
            return True
        return False
    bl = (body or "").lower()
    return (
        "aw, snap" in bl
        or "something went wrong while displaying this webpage" in bl
        or "error code: 5" in bl
        or "renderer process crashed" in bl
    )


async def recover_aw_snap(page, url: str, tag: str = "", context=None):
    """Recover after Aw Snap / closed page. Returns (ok, page) — page may be new."""
    prefix = f"  {tag}: " if tag else "  "
    cur = page
    for attempt in range(1, 4):
        closed = False
        try:
            closed = cur is None or cur.is_closed()
        except Exception:
            closed = True
        crashed = closed
        if not closed:
            try:
                crashed = await page_is_aw_snap(cur)
            except Exception:
                crashed = False
        if not crashed:
            return True, cur
        log(f"{prefix}Aw Snap/closed — recover attempt {attempt}/3")
        # Dead Playwright page object cannot reload — open a fresh tab.
        if closed and context is not None:
            try:
                nxt = await asyncio.wait_for(context.new_page(), timeout=15)
                try:
                    if cur is not None:
                        await asyncio.wait_for(cur.close(), timeout=5)
                except Exception:
                    pass
                cur = nxt
            except Exception as e:
                log(f"{prefix}new_page fail: {type(e).__name__}")
                return False, cur
        try:
            await safe_goto(cur, url, timeout_s=25)
        except Exception as e:
            log(f"{prefix}recover goto fail: {type(e).__name__}")
            # If goto closed the page again, loop will new_page next attempt
            try:
                if cur.is_closed() and context is not None:
                    cur = await asyncio.wait_for(context.new_page(), timeout=15)
            except Exception:
                pass
        # Aw Snap pages often respond to location.reload() via CDP even when
        # Playwright's page object is half-dead.
        try:
            if cur is not None and not cur.is_closed() and await page_is_aw_snap(cur):
                await asyncio.wait_for(
                    cur.evaluate("() => { location.reload(); return true; }"),
                    timeout=5,
                )
                await asyncio.sleep(3)
        except Exception:
            pass
        await asyncio.sleep(2)
        try:
            if cur is not None and not cur.is_closed() and not await page_is_aw_snap(cur):
                log(f"{prefix}page recovered")
                return True, cur
        except Exception:
            pass
    log(f"{prefix}still dead after 3 recovers")
    return False, cur


async def ensure_page_focused(page) -> None:
    """Force focused + visible on Xvfb: bring_to_front, CDP focus, click into page."""
    if page is None:
        return
    try:
        if page.is_closed():
            return
    except Exception:
        return
    # Never touch CDP/evaluate on a crashed tab — that hung Railway for hours.
    try:
        if await asyncio.wait_for(page_is_aw_snap(page), timeout=8):
            return
    except Exception:
        return
    try:
        await asyncio.wait_for(page.bring_to_front(), timeout=3)
    except Exception:
        pass
    # CDP: make target active (helps when Xvfb has no real WM focus)
    # new_cdp_session MUST be timed — hangs forever on Aw Snap / dead renderer.
    try:
        cdp = await asyncio.wait_for(
            page.context.new_cdp_session(page), timeout=5)
        try:
            await asyncio.wait_for(
                cdp.send("Page.bringToFront"), timeout=3)
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                cdp.send(
                    "Emulation.setFocusEmulationEnabled",
                    {"enabled": True},
                ),
                timeout=3,
            )
        except Exception:
            pass
        try:
            await cdp.detach()
        except Exception:
            pass
    except Exception:
        pass
    try:
        await asyncio.wait_for(
            page.evaluate(
                """() => {
                try { window.focus(); } catch (e) {}
                try {
                  Object.defineProperty(document, 'hidden', {
                    configurable: true, get: () => false
                  });
                  Object.defineProperty(document, 'visibilityState', {
                    configurable: true, get: () => 'visible'
                  });
                  document.dispatchEvent(new Event('visibilitychange'));
                  window.dispatchEvent(new Event('focus'));
                } catch (e) {}
                return {
                  hidden: document.hidden,
                  vis: document.visibilityState,
                  focus: document.hasFocus()
                };
            }"""
            ),
            timeout=5,
        )
    except Exception:
        pass
    # Physical click into content area so Chromium marks window active on Xvfb
    try:
        vp = page.viewport_size or {"width": VIEW_W, "height": VIEW_H}
        x = int(vp.get("width", VIEW_W) * 0.45)
        y = int(vp.get("height", VIEW_H) * 0.45)
        await asyncio.wait_for(page.mouse.move(x, y, steps=3), timeout=3)
        await asyncio.wait_for(page.mouse.click(x, y), timeout=3)
    except Exception:
        pass


def _chromium_lean_args() -> list:
    """Chromium stripped for Railway ~1GB — Lovable SPA + OOM = Aw Snap #5.

    Rules learned the hard way:
    - Do NOT use --max-old-space-size ≤256 (wedges CDP forever).
    - Do NOT keep a crashed browser open (eats the whole cgroup).
    - Block images/fonts via context routes, not by aborting documents.
    """
    return [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-gpu-compositing",
        "--in-process-gpu",
        "--remote-debugging-port=9222",
        # Match Xvfb + Playwright viewport (tiny 1024x576 blanked Lovable Preview)
        f"--window-size={VIEW_W},{VIEW_H}",
        "--window-position=0,0",
        "--force-device-scale-factor=1",
        # Low-end / single-site process model
        "--enable-low-end-device-mode",
        "--renderer-process-limit=1",
        "--process-per-site",
        "--disable-site-isolation-trials",
        # Modest V8 heap (384 OK; unlimited OOMs 1GB; ≤256 wedges CDP)
        "--js-flags=--max-old-space-size=384,--optimize-for-size",
        # Kill background / extras
        "--disable-background-networking",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-background-timer-throttling",
        "--disable-hang-monitor",
        "--disable-ipc-flooding-protection",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-client-side-phishing-detection",
        "--disable-sync",
        "--disable-translate",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-breakpad",
        "--disable-crash-reporter",
        "--metrics-recording-only",
        "--mute-audio",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-zygote",
        "--disable-features=AudioServiceOutOfProcess,IsolateOrigins,"
        "site-per-process,TranslateUI,BackForwardCache,AcceptCHFrame,"
        "MediaRouter,OptimizationHints,PaintHolding,"
        "CalculateNativeWinOcclusion,IntensiveWakeUpThrottling,"
        "InterestFeedContentSuggestions,CertificateTransparencyComponentUpdater",
        # Tiny caches
        "--disk-cache-size=1048576",
        "--media-cache-size=1048576",
        "--aggressive-cache-discard",
        "--disable-remote-fonts",
        "--blink-settings=imagesEnabled=false",
    ]


async def install_memory_guards(context) -> None:
    """Drop images/fonts/media only — never block document/script/xhr (hangs goto)."""
    if context is None:
        return

    _ASSET_EXT = (
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
        ".avif", ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp4", ".webm", ".mp3", ".wav", ".ogg", ".m4a",
    )

    async def _drop(route):
        try:
            url = (route.request.url or "").lower().split("?", 1)[0]
            if any(url.endswith(ext) for ext in _ASSET_EXT):
                await route.abort()
            else:
                await route.continue_()
        except Exception:
            try:
                await route.continue_()
            except Exception:
                pass

    try:
        await context.route("**/*", _drop)
        log("  Memory guards: block images/fonts/media (scripts OK)")
    except Exception as e:
        log(f"  Memory guards soft-fail: {type(e).__name__}")
        log("  Memory guards: lean Chrome flags only")


async def find_chat_composer(page, tag: str = ""):
    """Find contenteditable fast. JS probe FIRST — click loops hang CDP on Railway.

    Returns (locator_or_None, cdp_hung: bool).
    cdp_hung only when JS *and* locator probes all hard-timeout (true wedge).
    On ~1GB cells, skip the opening evaluate (it Aw-Snaps a hydrating SPA).
    """
    if page is None:
        return None, False
    tag_s = f" {tag}" if tag else ""
    js_timed_out = False
    low_mem = bool(cgroup_mem_gb() and cgroup_mem_gb() <= 1.15)

    # 1) Fast JS count (hard 8s) — skipped on 1GB (evaluate → Target crashed)
    if low_mem:
        log(f"  Composer: skip JS probe on 1GB{tag_s} — locators only")
    else:
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
            log(f"  Composer: JS probe fail ({type(e).__name__}: {e}){tag_s}")
            if _is_crash_error(e):
                log(f"  Composer: target dead{tag_s} — treat as hung (fresh tab)")
                return None, True

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
    session_id: str | None = None,
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
            log("  Wake: CDP hung on fast path — tab wedged")
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

        # Login / private-project access wall → refresh_token then back
        on_login = "/login" in cur or "/auth" in cur
        if not on_login:
            try:
                on_login = await detect_auth_wall(chat_page)
            except Exception:
                on_login = False
        if on_login and (session_config or session_id):
            log("  Wake: access/login wall — refresh_token first")
            sid = session_id or (session_config or {}).get("session_id")
            ok = await ensure_authed(
                chat_page,
                sid,
                session_config,
                target_url=chat_url,
            )
            if not ok:
                log("  Wake: auth revive failed")
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
            log("  Wake: CDP hung — tab wedged")
            return False

        log(f"  Wake: no composer yet — refresh again")
        await asyncio.sleep(2)

    if not chat_input:
        log(f"  Wake: chat input not found after {WAKE_ROUNDS} refreshes")
        return False

    return await _type_and_send(chat_input, _rand.choice(WAKE_PROMPTS))


async def human_mouse_to(page, x: float, y: float) -> None:
    """Bezier path + Fitts-ish timing + optional overshoot (ghost-cursor style).

    Humans: curved paths, slow-fast-slow velocity, micro-jitter, ~55% overshoot
    on longer moves, then a short correction. Uses Playwright mouse (trusted).
    """
    import math
    import random as _r

    x0 = float(_HUMAN_MOUSE.get("x", 640))
    y0 = float(_HUMAN_MOUSE.get("y", 400))
    x1, y1 = float(x), float(y)
    dist = math.hypot(x1 - x0, y1 - y0)
    if dist < 3:
        _HUMAN_MOUSE["x"], _HUMAN_MOUSE["y"] = x1, y1
        return

    # Perpendicular offset for cubic control points (asymmetric curve)
    dx, dy = x1 - x0, y1 - y0
    px, py = -dy / dist, dx / dist
    spread = min(120.0, dist * _r.uniform(0.15, 0.45))
    c1x = x0 + dx * _r.uniform(0.2, 0.4) + px * _r.uniform(-spread, spread)
    c1y = y0 + dy * _r.uniform(0.2, 0.4) + py * _r.uniform(-spread, spread)
    c2x = x0 + dx * _r.uniform(0.55, 0.8) + px * _r.uniform(-spread, spread)
    c2y = y0 + dy * _r.uniform(0.55, 0.8) + py * _r.uniform(-spread, spread)

    overshoot = dist > 100 and _r.random() < 0.55
    tx, ty = x1, y1
    if overshoot:
        ox = (dx / dist) * _r.uniform(8, 24)
        oy = (dy / dist) * _r.uniform(8, 24)
        tx, ty = x1 + ox, y1 + oy
        # retarget bezier end at overshoot, then correct
        x1, y1 = tx, ty

    steps = max(8, min(28, int(dist / 14) + _r.randint(0, 4)))
    # Fitts-ish: MT ≈ a + b·log2(D/W + 1); W~40px target
    duration = 0.08 + 0.12 * math.log2(dist / 40.0 + 1.0)
    duration *= _r.uniform(0.85, 1.15)

    def _bez(t: float):
        u = 1.0 - t
        bx = (u ** 3) * x0 + 3 * (u ** 2) * t * c1x + 3 * u * (t ** 2) * c2x + (t ** 3) * x1
        by = (u ** 3) * y0 + 3 * (u ** 2) * t * c1y + 3 * u * (t ** 2) * c2y + (t ** 3) * y1
        # micro tremor
        bx += _r.gauss(0, 0.6)
        by += _r.gauss(0, 0.6)
        return bx, by

    # Ease-in-out sample density (more points near ends = slower ends)
    for i in range(1, steps + 1):
        t_lin = i / steps
        # smoothstep for velocity bell (spend more time at ends)
        t = t_lin * t_lin * (3 - 2 * t_lin)
        bx, by = _bez(t)
        await page.mouse.move(bx, by)
        # variable poll ~60–120Hz
        await asyncio.sleep(duration / steps * _r.uniform(0.7, 1.4))
        # rare mid-path hesitation
        if _r.random() < 0.04:
            await asyncio.sleep(_r.uniform(0.04, 0.12))

    if overshoot:
        # correction back to true target
        for i in range(1, 6):
            t = i / 5
            cx = tx + (float(x) - tx) * t + _r.gauss(0, 0.3)
            cy = ty + (float(y) - ty) * t + _r.gauss(0, 0.3)
            await page.mouse.move(cx, cy)
            await asyncio.sleep(_r.uniform(0.012, 0.028))
        x1, y1 = float(x), float(y)

    _HUMAN_MOUSE["x"], _HUMAN_MOUSE["y"] = x1, y1


async def human_type_text(page, text: str) -> None:
    """Per-char typing with human IKI (~60–450ms; mean ~180ms from keystroke studies)."""
    import random as _r

    for i, ch in enumerate(text):
        await page.keyboard.type(ch, delay=0)
        # Inter-key interval: roughly lognormal around 180ms
        iki = _r.gauss(180, 70)
        iki = max(55, min(480, iki))
        # word / planning pauses (longer at spaces and every few chars)
        if ch == " " or (i > 0 and i % 4 == 0 and _r.random() < 0.2):
            iki += _r.uniform(90, 280)
        # rare typo + backspace
        if _r.random() < 0.06 and ch.isalnum():
            wrong = _r.choice("abcdefghijklmnopqrstuvwxyz")
            await page.keyboard.type(wrong, delay=0)
            await asyncio.sleep(_r.uniform(0.08, 0.22))
            await page.keyboard.press("Backspace")
            await asyncio.sleep(_r.uniform(0.05, 0.12))
        await asyncio.sleep(iki / 1000.0)


async def human_scroll(page, amount: int | None = None) -> None:
    """Chunked wheel with logarithmic feel — not one huge jump."""
    import random as _r

    total = amount if amount is not None else _r.choice([-180, -120, -80, 80, 120, 180])
    sign = 1 if total > 0 else -1
    left = abs(total)
    while left > 0:
        step = min(left, _r.randint(40, 90))
        await page.mouse.wheel(0, sign * step)
        left -= step
        await asyncio.sleep(_r.uniform(0.04, 0.14))
    # tiny settle
    if _r.random() < 0.35:
        await page.mouse.wheel(0, -sign * _r.randint(10, 30))
        await asyncio.sleep(_r.uniform(0.05, 0.12))


async def keep_pages_warm(chat_page, preview_page, light: bool = False) -> None:
    """Human-like presence: Bezier mouse, scroll chunks, light type, reading pauses.

    light=True (babysit under mem pressure): mouse+scroll only — no evaluate,
    no composer typing. Cuts CDP load that triggers Aw Snap on 1GB.
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
            # JS soft-scroll — skipped in light mode (evaluate Aw-Snaps on 1GB)
            if not light:
                try:
                    await asyncio.wait_for(page.evaluate("""() => {
                        const scrolls = [
                            ...document.querySelectorAll(
                              '[data-radix-scroll-area-viewport], .overflow-y-auto, [class*="overflow-y"]')
                        ].filter(el => el.scrollHeight > el.clientHeight + 40);
                        if (scrolls.length) {
                            const el = scrolls[0];
                            const delta = (Math.random() > 0.5 ? 1 : -1) * (40 + Math.random() * 120);
                            el.scrollTop = Math.max(0, Math.min(el.scrollHeight, el.scrollTop + delta));
                        }
                        window.dispatchEvent(new Event('focus'));
                        document.dispatchEvent(new Event('visibilitychange'));
                        return true;
                    }"""), timeout=5)
                except Exception:
                    pass

            await asyncio.sleep(_r.uniform(0.15, 0.5 if light else 0.9))

            vp = page.viewport_size or {"width": VIEW_W, "height": VIEW_H}
            w, h = int(vp.get("width", VIEW_W)), int(vp.get("height", VIEW_H))
            cx = _r.uniform(w * 0.12, w * 0.38)
            cy = _r.uniform(h * 0.32, h * 0.78)
            px = _r.uniform(w * 0.52, w * 0.90)
            py = _r.uniform(h * 0.32, h * 0.78)

            await human_mouse_to(page, cx, cy)
            await asyncio.sleep(_r.uniform(0.1, 0.3))
            await human_scroll(page)
            await asyncio.sleep(_r.uniform(0.08, 0.25))
            await human_mouse_to(page, px, py)
            if light:
                # Arrow key only — no click, no composer type
                key = _r.choice(PRESENCE_KEYS)
                await page.keyboard.press(key)
                log(f"  Presence poke light ({label}: mouse/scroll/{key})")
                return

            await asyncio.sleep(_r.uniform(0.1, 0.3))
            await human_scroll(page)
            if _r.random() < 0.30:
                await asyncio.sleep(_r.uniform(0.08, 0.22))
                await page.mouse.click(px, py)
                await asyncio.sleep(_r.uniform(0.1, 0.25))
            await human_mouse_to(
                page,
                px + _r.uniform(-50, 50),
                py + _r.uniform(-40, 40),
            )
            key = _r.choice(PRESENCE_KEYS)
            await page.keyboard.press(key)
            if _r.random() < 0.6:
                try:
                    await asyncio.wait_for(page.evaluate("""() => {
                        const el = document.querySelector(
                          'div[contenteditable="true"][role="textbox"], '
                          + '[contenteditable="true"], textarea');
                        if (el) { el.focus(); return true; }
                        return false;
                    }"""), timeout=2)
                    await asyncio.sleep(_r.uniform(0.2, 0.6))
                    snippet = _r.choice(("ok", "hi", "a", "x", "1", "yo"))
                    await human_type_text(page, snippet)
                    await asyncio.sleep(_r.uniform(0.2, 0.5))
                    for _ in range(len(snippet) + 2):
                        await page.keyboard.press("Backspace")
                        await asyncio.sleep(_r.uniform(0.04, 0.11))
                    await page.keyboard.press("Escape")
                except Exception:
                    pass
            log(f"  Presence poke ok ({label}: bezier/scroll/type/{key})")

        try:
            tout = 12 if light else PRESENCE_POKE_TIMEOUT_S
            await asyncio.wait_for(_do(), timeout=tout)
        except asyncio.TimeoutError:
            log(f"  Presence poke timeout ({label})")
        except Exception as e:
            if _is_crash_error(e):
                raise
            log(f"  Presence poke soft-fail ({label}): {type(e).__name__}")

    same = preview_page is chat_page
    await _human_chat(chat_page, "chat+preview" if same else "chat")
    if light:
        return
    if not same and preview_page is not None:
        async def _poke_preview():
            import random as _r2
            try:
                await preview_page.bring_to_front()
            except Exception:
                pass
            vp = preview_page.viewport_size or {"width": VIEW_W, "height": VIEW_H}
            w, h = int(vp.get("width", VIEW_W)), int(vp.get("height", VIEW_H))
            x = _r2.uniform(80, max(100, w - 80))
            y = _r2.uniform(80, max(100, h - 80))
            await human_mouse_to(preview_page, x, y)
            await human_scroll(preview_page)
            if _r2.random() < 0.35:
                await preview_page.mouse.click(x, y)
            await preview_page.keyboard.press(_r2.choice(PRESENCE_KEYS))
            log("  Presence poke ok (preview: bezier/scroll)")
        try:
            await asyncio.wait_for(_poke_preview(), timeout=PRESENCE_POKE_TIMEOUT_S)
        except asyncio.TimeoutError:
            log(f"  Presence poke timeout (preview >{PRESENCE_POKE_TIMEOUT_S}s)")
        except Exception as e:
            if _is_crash_error(e):
                raise
            log(f"  Presence poke soft-fail (preview): {type(e).__name__}")


async def dismiss_blocking_popups(chat_page, *, max_passes: int = 5) -> bool:
    """Keep closing upgrade / credits / cookie dialogs until none left.

    Upgrade modal often reappears — loop Cancel/X/Escape each pass.
    """
    if chat_page is None:
        return False
    try:
        if chat_page.is_closed():
            return False
    except Exception:
        return False
    any_closed = False
    try:
        await asyncio.wait_for(chat_page.bring_to_front(), timeout=5)
    except Exception:
        pass

    for pass_n in range(1, max_passes + 1):
        closed_this = False

        # Prefer Cancel inside an open dialog (Upgrade your plan)
        try:
            dlg = chat_page.locator('[role="dialog"]')
            n_dlg = await asyncio.wait_for(dlg.count(), timeout=1.5)
            if n_dlg > 0:
                for name in ("Cancel", "Not now", "Close", "Maybe later",
                             "OK", "Accept", "Accept all"):
                    try:
                        btn = dlg.last.get_by_role(
                            "button", name=name, exact=False)
                        if await btn.count() and await btn.first.is_visible(
                                timeout=600):
                            await btn.first.click(timeout=2000)
                            log(f"  Popup: closed dialog '{name}' (pass {pass_n})")
                            closed_this = True
                            break
                    except Exception:
                        continue
                if not closed_this:
                    # bare text Cancel inside dialog
                    try:
                        btn = dlg.last.locator(
                            'button:has-text("Cancel")').first
                        if await btn.is_visible(timeout=600):
                            await btn.click(timeout=2000)
                            log(f"  Popup: closed dialog Cancel text (pass {pass_n})")
                            closed_this = True
                    except Exception:
                        pass
        except Exception:
            pass

        if not closed_this:
            for label in POPUP_DISMISS_LABELS:
                try:
                    btn = chat_page.get_by_role(
                        "button", name=label, exact=False)
                    n = await asyncio.wait_for(btn.count(), timeout=1.2)
                    if n <= 0:
                        continue
                    if not await btn.first.is_visible(timeout=600):
                        continue
                    await btn.first.click(timeout=2000)
                    log(f"  Popup: closed '{label}' (pass {pass_n})")
                    closed_this = True
                    break
                except Exception:
                    continue

        if not closed_this:
            for sel in (
                '[role="dialog"] button[aria-label*="Close" i]',
                '[role="dialog"] button[aria-label*="Dismiss" i]',
                '[data-state="open"] button[aria-label*="Close" i]',
            ):
                try:
                    loc = chat_page.locator(sel).first
                    if await loc.count() and await loc.is_visible(timeout=500):
                        await loc.click(timeout=1500)
                        log(f"  Popup: closed via X (pass {pass_n})")
                        closed_this = True
                        break
                except Exception:
                    continue

        # Always Escape once per pass — cheap, clears many overlays
        try:
            await chat_page.keyboard.press("Escape")
        except Exception:
            pass

        if closed_this:
            any_closed = True
            await asyncio.sleep(0.5)
            continue
        # nothing left to close
        break

    return any_closed


async def refresh_chat_for_presence(chat_page, chat_url: str | None = None) -> bool:
    """Reload chat (after popup close or 2min tick). Soft-fail."""
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
    try:
        cur = ""
        try:
            cur = chat_page.url or ""
        except Exception:
            cur = ""
        log("  Presence refresh: reloading chat")
        if chat_url and chat_url.rstrip("/") in (cur.split("?")[0] or ""):
            await chat_page.reload(timeout=45000, wait_until="commit")
        elif chat_url:
            await chat_page.goto(chat_url, timeout=45000, wait_until="commit")
        else:
            await chat_page.reload(timeout=45000, wait_until="commit")
        await asyncio.sleep(4)
        await light_focus(chat_page)
        # popups often reappear after reload — close again
        await dismiss_blocking_popups(chat_page)
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
        # Human: move to composer, hesitate, click, think, type with IKI variance
        try:
            box = await chat_input.bounding_box()
        except Exception:
            box = None
        if box:
            tx = box["x"] + box["width"] * _rand.uniform(0.25, 0.75)
            ty = box["y"] + box["height"] * _rand.uniform(0.3, 0.7)
            await human_mouse_to(chat_page, tx, ty)
            await asyncio.sleep(_rand.uniform(0.08, 0.25))
            await chat_page.mouse.click(tx, ty)
        else:
            try:
                await chat_input.click(timeout=3000)
            except Exception:
                pass
        await asyncio.sleep(_rand.uniform(0.2, 0.7))  # think before typing
        try:
            # clear any leftover text first
            await chat_page.keyboard.press("Control+a")
            await asyncio.sleep(0.05)
            await chat_page.keyboard.press("Backspace")
            await asyncio.sleep(_rand.uniform(0.1, 0.25))
            await human_type_text(chat_page, prompt)
        except Exception as e:
            log(f"  Presence prompt type fail: {type(e).__name__}")
            try:
                await chat_input.fill(prompt, timeout=5000)
            except Exception:
                return False
        await asyncio.sleep(_rand.uniform(0.15, 0.4))  # glance before send
        try:
            send_btn = chat_page.locator(
                'button[data-testid="chat-input-send"], '
                'button[aria-label*="Send" i]'
            ).first
            if await send_btn.count() and await send_btn.is_visible(timeout=1500):
                try:
                    sb = await send_btn.bounding_box()
                except Exception:
                    sb = None
                if sb:
                    await human_mouse_to(
                        chat_page,
                        sb["x"] + sb["width"] / 2,
                        sb["y"] + sb["height"] / 2,
                    )
                    await asyncio.sleep(_rand.uniform(0.05, 0.15))
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


async def type_idle_text(chat_page) -> bool:
    """Type into the composer WITHOUT submitting (zero credits).

    Keydown/input/focus activity that reads as an active user thinking.
    Clears the text afterwards (80%) or leaves it mid-thought (20%).
    Soft-fail unless crash — same contract as send_presence_prompt.
    """
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
            chat_page, tag="idle-type")
        if cdp_hung:
            raise asyncio.TimeoutError("cdp hung on idle-type composer")
        if not chat_input:
            return False
        phrase = _rand.choice(IDLE_TYPE_PHRASES)
        try:
            box = await chat_input.bounding_box()
        except Exception:
            box = None
        if box:
            tx = box["x"] + box["width"] * _rand.uniform(0.25, 0.75)
            ty = box["y"] + box["height"] * _rand.uniform(0.3, 0.7)
            await human_mouse_to(chat_page, tx, ty)
            await asyncio.sleep(_rand.uniform(0.08, 0.25))
            await chat_page.mouse.click(tx, ty)
        else:
            try:
                await chat_input.click(timeout=3000)
            except Exception:
                pass
        await asyncio.sleep(_rand.uniform(0.2, 0.7))  # think before typing
        try:
            # clear leftovers first so text never accumulates
            await chat_page.keyboard.press("Control+a")
            await asyncio.sleep(0.05)
            await chat_page.keyboard.press("Backspace")
            await asyncio.sleep(_rand.uniform(0.1, 0.25))
            await human_type_text(chat_page, phrase)
        except Exception as e:
            log(f"  Idle-type fail: {type(e).__name__}")
            return False
        await asyncio.sleep(_rand.uniform(1.0, 3.0))  # stare at it, thinking
        if _rand.random() < 0.8:
            try:
                await chat_page.keyboard.press("Control+a")
                await asyncio.sleep(0.05)
                await chat_page.keyboard.press("Backspace")
            except Exception:
                pass
            log("  Idle-type: typed + cleared (no submit)")
        else:
            log("  Idle-type: left mid-thought (no submit)")
        return True

    try:
        return await asyncio.wait_for(_do(), timeout=PRESENCE_PROMPT_TIMEOUT_S)
    except asyncio.TimeoutError:
        log("  Idle-type timeout (CDP?)")
        return False
    except Exception as e:
        if _is_crash_error(e):
            raise
        log(f"  Idle-type soft-fail: {type(e).__name__}")
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


async def force_preview_to_lovableproject_term(chat_page, project_id: str) -> bool:
    """When stuck on id-preview / cold mirrors, push a frame to real Shell /term.

    Fresh-tab recoveries often land on id-preview forever (no window.doc). The
    known project id is enough to retarget: https://{id}.lovableproject.com/term
    """
    if not project_id or chat_page is None:
        return False
    dest = f"https://{project_id}.lovableproject.com/term"
    try:
        await ensure_preview_shell_panel(chat_page)
    except Exception:
        pass
    frames = []
    try:
        frames = list(chat_page.frames)
    except Exception:
        return False

    def _score(fr) -> int:
        try:
            u = (fr.url or "").lower()
        except Exception:
            return -1
        if "lovable.dev" in u and "lovableproject" not in u:
            return -1
        if "lovableproject.com" in u:
            return 100 if "/term" in u else 80
        if "id-preview" in u or ("lovable.app" in u and "preview" in u):
            return 50
        if "webcontainer" in u or "stackblitz" in u:
            return 40
        try:
            if fr != chat_page.main_frame and (not u or u.startswith("about:")):
                return 20
        except Exception:
            pass
        return -1

    ranked = sorted((( _score(fr), fr) for fr in frames), key=lambda x: -x[0])
    ranked = [(s, fr) for s, fr in ranked if s > 0]
    if not ranked:
        # Preview panel missing entirely — remount once, rescan (cell-35 wedge).
        try:
            await ensure_preview_shell_panel(chat_page)
            await asyncio.sleep(2)
            frames = list(chat_page.frames)
            ranked = sorted(((_score(fr), fr) for fr in frames), key=lambda x: -x[0])
            ranked = [(s, fr) for s, fr in ranked if s > 0]
        except Exception:
            ranked = []
        if not ranked:
            log(f"  Force /term: no preview-ish frame for {dest}")
            return False
    for sc, fr in ranked[:3]:
        try:
            cur = (fr.url or "")[:100]
        except Exception:
            cur = "?"
        # Already on good /term with doc — leave it
        if sc >= 100:
            probe = await _probe_frame_doc_nproc(fr, timeout=6.0)
            if isinstance(probe, dict) and probe.get("ok"):
                log(f"  Force /term: already OK @ {cur}")
                return True
            if "lovableproject.com" in cur and "/term" not in cur.lower():
                pass  # fall through to goto /term
            elif "lovableproject.com" in cur and "/term" in cur.lower():
                continue  # doc not ready yet; try another frame
        navigated = False
        try:
            log(f"  Force /term: navigate score={sc} {cur[:80]} → {dest}")
            await asyncio.wait_for(
                fr.goto(dest, wait_until="domcontentloaded", timeout=25000),
                timeout=30,
            )
            navigated = True
        except Exception as e:
            # Under 1GB CRITICAL, frame.goto often TimeoutError — JS assign
            # still remounts Shell without waiting on full load events.
            log(f"  Force /term soft: {type(e).__name__} — try location.assign")
            try:
                await asyncio.wait_for(
                    fr.evaluate("(u) => { location.href = u; }", dest),
                    timeout=8,
                )
                navigated = True
            except Exception as e2:
                log(f"  Force /term assign soft: {type(e2).__name__}")
                continue
        if not navigated:
            continue
        try:
            await asyncio.sleep(3)
            probe = await _probe_frame_doc_nproc(fr, timeout=12.0)
            if isinstance(probe, dict) and probe.get("ok"):
                log(f"  Force /term: DOC ok nproc={probe.get('r')!r}")
                return True
        except Exception as e:
            log(f"  Force /term probe soft: {type(e).__name__}")
            continue
    return False


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


async def _probe_frame_doc_nproc(fr, timeout: float = 8.0):
    """Hard-bounded doc gate: real bridge = window.doc('nproc') returns stdout.

    Script3-style — typeof alone is not enough; cmd must run on lovableproject.
    """
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
                    const r = await window.doc('nproc');
                    const out = (r && (r.stdout !== undefined ? r.stdout : r)) + '';
                    const code = (r && r.code !== undefined) ? r.code : null;
                    // nproc prints a number — require non-empty stdout and no shell fail
                    const ok = !!(out.trim()) && (code === null || code === 0);
                    return { ok: ok, r: out.trim().slice(0, 80), code: code,
                             err: ok ? null : ('nproc-empty-or-fail code=' + code) };
                } catch (e) {
                    return { ok: false, err: String(e && e.message || e).slice(0, 120) };
                }
            }"""
            ),
            timeout=timeout,
        )
    except Exception as e:
        return {"ok": False, "err": type(e).__name__}


# Back-compat alias (call sites / older patches)
_probe_frame_doc_pwd = _probe_frame_doc_nproc


async def wait_for_chat_preview_sandbox(
    chat_page,
    timeout_seconds: int = 120,
    require_lovableproject: bool = True,
) -> bool:
    """Wait until chat Preview exposes window.doc — preferably in lovableproject iframe.

    Probes only top-ranked frames with short timeouts so CDP wedges cannot
    stall past timeout_seconds. Remounts Preview/Shell while waiting.
    """
    want = "lovableproject+doc" if require_lovableproject else "any-doc"
    log(f"Waiting for chat Preview {want} (max {timeout_seconds}s)...")
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

        # Squash upgrade/credits popup every pass — it reappears after prompts
        try:
            await dismiss_blocking_popups(chat_page, max_passes=3)
        except Exception:
            pass

        # Remount Preview/Shell periodically — iframe often appears only after remount
        if elapsed - last_remount >= 20:
            last_remount = elapsed
            try:
                await asyncio.wait_for(
                    ensure_preview_shell_panel(chat_page), timeout=20)
            except Exception as e:
                last_note = f"remount:{type(e).__name__}"
            try:
                await dismiss_blocking_popups(chat_page, max_passes=2)
            except Exception:
                pass

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
        candidates = ranked[:5]

        if elapsed - last_tick >= 12:
            last_tick = elapsed
            urls = []
            has_lp = False
            for sc, fr in candidates:
                try:
                    u = (fr.url or "")[:55]
                    if "lovableproject.com" in u:
                        has_lp = True
                except Exception:
                    u = "?"
                urls.append(f"{sc}:{u}")
            log(f"  Looking iframe {int(elapsed)}s "
                f"frames={len(frames)} lovableproject={'yes' if has_lp else 'NO'} "
                f"[{', '.join(urls) or 'none'}] last={last_note or '-'}")

        soft = None
        for sc, fr in candidates:
            try:
                u = fr.url or ""
            except Exception:
                u = ""
            ul = u.lower()
            # Bridge often lives on /term (Build a debug terminal), not Homepage
            if "lovableproject.com" in ul and "/term" not in ul:
                try:
                    import re as _re_term
                    m = _re_term.match(
                        r"(https://[^/]+\.lovableproject\.com)", u.split("?")[0])
                    if m:
                        dest = m.group(1) + "/term"
                        log(f"  Navigate lovableproject → /term")
                        await asyncio.wait_for(
                            fr.goto(dest, wait_until="domcontentloaded",
                                    timeout=20000),
                            timeout=25,
                        )
                        await asyncio.sleep(1.5)
                        try:
                            u = fr.url or dest
                            ul = u.lower()
                        except Exception:
                            u, ul = dest, dest.lower()
                except Exception as e:
                    last_note = f"term-nav:{type(e).__name__}"
            probe = await _probe_frame_doc_nproc(fr, timeout=8.0)
            if not isinstance(probe, dict):
                continue
            if not probe.get("ok"):
                err = str(probe.get("err", "?"))[:50]
                if sc >= 20:
                    last_note = f"{u[:70]}:{err}"
                continue
            nproc_out = str(probe.get("r", "")).strip()
            if "lovableproject.com" in ul:
                log(f"  DOC_MARK=OK doc('nproc')→{nproc_out!r} @ {u[:100]}")
                log(f"  Chat Preview sandbox ready (lovableproject+nproc): {u[:120]}")
                return True
            soft = soft or (u, nproc_out)
        if soft and not require_lovableproject:
            u_soft, n_soft = soft if isinstance(soft, tuple) else (soft, "")
            log(f"  DOC_MARK=OK doc('nproc')→{n_soft!r} @ {str(u_soft)[:100]}")
            log(f"  Chat Preview sandbox ready (nproc): {str(u_soft)[:120]}")
            return True
        await asyncio.sleep(4)


async def bring_up_lovableproject_doc(
    chat_page,
    *,
    max_rounds: int = 0,
    wait_per_round_s: int = 75,
    project_id: str = "",
    session_id=None,
    session_config: dict | None = None,
    chat_url: str = "",
) -> bool:
    """After prompting: keep remounting Preview + scanning for lovableproject iframe
    with working window.doc('nproc') until it shows up.

    max_rounds=0 means keep going until the page dies (startup / forever bring-up),
    but blank white Preview (/term:no-doc) triggers soft chat reload every
    BLANK_PREVIEW_RELOAD_ROUNDS, then hard browser relaunch at
    BLANK_PREVIEW_HARD_ROUNDS — do not sit forever on a dead shell.
    No full-page reload on every miss — remount Preview/Shell + tiny prompts only.
    When project_id is set, every failed round force-navigates id-preview → /term
    so recoveries do not wedge on cold mirrors forever.
    If the SPA shows 'You don't have access' / login, refresh_token and reload.
    """
    round_n = 0
    dest = chat_url or (
        f"https://lovable.dev/projects/{project_id}" if project_id else ""
    )
    while True:
        round_n += 1
        if max_rounds and round_n > max_rounds:
            log(f"  lovableproject+doc not up after {max_rounds} rounds")
            return False
        # Forever bring-up only: blank iframe for too long → refresh / relaunch
        if not max_rounds and round_n > BLANK_PREVIEW_HARD_ROUNDS:
            log(f"  Blank Preview {round_n} rounds — hard-kill browser + relaunch")
            try:
                hard_kill_chrome()
            except Exception:
                pass
            raise RuntimeError("aw-snap-relaunch")
        try:
            if chat_page is None or chat_page.is_closed():
                log("  bring_up: page closed")
                return False
        except Exception:
            return False

        # Stale cookies → private-project wall with no Preview iframe.
        # Detect + refresh_token before another empty remount cycle.
        if (session_id or session_config) and (round_n == 1 or round_n % 3 == 1):
            try:
                if await detect_auth_wall(chat_page):
                    log(f"  Bring-up: access/login wall — refresh_token (r{round_n})")
                    ok = await ensure_authed(
                        chat_page,
                        session_id,
                        session_config,
                        target_url=dest or None,
                    )
                    if ok and dest:
                        try:
                            await chat_page.goto(
                                dest, timeout=40000, wait_until="domcontentloaded")
                            await asyncio.sleep(4)
                        except Exception as e:
                            log(f"  Bring-up post-auth goto soft: {type(e).__name__}")
                    elif not ok:
                        log("  Bring-up: auth revive failed — keep trying")
            except Exception as e:
                log(f"  Bring-up auth check soft: {type(e).__name__}")

        log(f"  Bring-up lovableproject iframe+doc "
            f"(round {round_n}{'' if not max_rounds else f'/{max_rounds}'})...")
        try:
            await ensure_page_focused(chat_page)
        except Exception:
            pass
        try:
            await dismiss_blocking_popups(chat_page, max_passes=5)
        except Exception:
            pass
        try:
            await ensure_preview_shell_panel(chat_page)
        except Exception as e:
            log(f"  Panel remount soft: {type(e).__name__}")
        try:
            await dismiss_blocking_popups(chat_page, max_passes=3)
        except Exception:
            pass
        try:
            await asyncio.wait_for(
                steal_preview_url_from_chat(chat_page), timeout=25)
        except Exception:
            pass
        # Odd rounds: force id-preview → real lovableproject /term (known project).
        if project_id and (round_n == 1 or round_n % 2 == 1):
            try:
                if await force_preview_to_lovableproject_term(chat_page, project_id):
                    return True
            except Exception as e:
                log(f"  Force /term skip: {type(e).__name__}")

        ready = await wait_for_chat_preview_sandbox(
            chat_page,
            timeout_seconds=wait_per_round_s,
            require_lovableproject=True,
        )
        if ready:
            return True

        log("  Still no lovableproject+doc — close popups, prompt, remount, keep looking")
        if project_id:
            try:
                await force_preview_to_lovableproject_term(chat_page, project_id)
            except Exception:
                pass
        try:
            await dismiss_blocking_popups(chat_page, max_passes=5)
        except Exception:
            pass
        try:
            await asyncio.wait_for(send_presence_prompt(chat_page), timeout=40)
        except Exception as e:
            log(f"  Bring-up prompt skip: {type(e).__name__}")
        try:
            await dismiss_blocking_popups(chat_page, max_passes=3)
        except Exception:
            pass
        try:
            await ensure_preview_shell_panel(chat_page)
        except Exception:
            pass

        # Soft refresh: blank white Preview for N rounds → reload chat tab
        if (
            not max_rounds
            and BLANK_PREVIEW_RELOAD_ROUNDS > 0
            and round_n % BLANK_PREVIEW_RELOAD_ROUNDS == 0
            and dest
        ):
            log(f"  Blank Preview {round_n} rounds — refresh browser (reload chat)")
            try:
                await chat_page.goto(
                    dest, timeout=40000, wait_until="domcontentloaded")
                await asyncio.sleep(5)
                await dismiss_blocking_popups(chat_page, max_passes=5)
                await ensure_preview_shell_panel(chat_page)
                if project_id:
                    try:
                        await force_preview_to_lovableproject_term(
                            chat_page, project_id)
                    except Exception:
                        pass
            except Exception as e:
                log(f"  Blank refresh soft-fail: {type(e).__name__}")

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
    session_id: str | None = None,
) -> bool:
    """
    Recover shell/worker.
    Iframe mode: soft re-inject first (NO chat reload) — reload wedges CDP on Railway.
    Separate preview tab: wake → goto → inject.
    """
    from miner_injector import inject_miner

    same_page = preview_page is chat_page
    proj = ""
    try:
        import re as _re_pid
        for src in (preview_url or "", chat_url or ""):
            m = _re_pid.search(
                r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
                src or "",
            )
            if m:
                proj = m.group(1)
                break
    except Exception:
        proj = ""
    if same_page:
        log("  Revive: iframe soft path — bring up lovableproject+doc + reinject")
        try:
            await asyncio.wait_for(
                steal_preview_url_from_chat(chat_page), timeout=30)
        except Exception as e:
            log(f"  Revive steal fail: {type(e).__name__}")
        if proj:
            try:
                await force_preview_to_lovableproject_term(chat_page, proj)
            except Exception:
                pass
        ready = await bring_up_lovableproject_doc(
            chat_page, max_rounds=4, wait_per_round_s=60, project_id=proj,
            session_id=session_id, session_config=session_config,
            chat_url=chat_url or "")
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
        log("  Revive: soft path missed — more prompt + remount (no reload)")
        await dismiss_blocking_popups(chat_page)
        await send_presence_prompt(chat_page)
        await ensure_preview_shell_panel(chat_page)
        if proj:
            try:
                await force_preview_to_lovableproject_term(chat_page, proj)
            except Exception:
                pass
        ready = await bring_up_lovableproject_doc(
            chat_page, max_rounds=3, wait_per_round_s=60, project_id=proj,
            session_id=session_id, session_config=session_config,
            chat_url=chat_url or "")
        if not ready:
            log("  Revive: lovableproject+doc never ready (iframe)")
            return False
        log("  Revive: injecting worker into chat Preview iframe")
        ok = await inject_miner(chat_page, bridge_url, threads)
        log(f"  Revive inject: {'OK' if ok else 'FAILED'}")
        return bool(ok)

    log("  Revive: refresh chat → wake → wait → preview → inject")
    woke = await send_wake_prompt(
        chat_page,
        chat_url=chat_url,
        session_config=session_config,
        session_id=session_id,
    )
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
            chat_page,
            chat_url=chat_url,
            session_config=session_config,
            session_id=session_id,
        )
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
    # Private-project modal keeps /projects URL but blocks Preview iframe.
    try:
        if await detect_auth_wall(preview_page):
            return False, "auth-wall"
    except Exception:
        pass

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


async def save_trio(context, page, session_id, *, force_idb: bool = False):
    """Save cookies + localStorage + IndexedDB to disk.

    force_idb=True writes IndexedDB even when CHIMERA_SKIP_IDB=1 (post-refresh).
    """
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
    if os.environ.get("CHIMERA_SKIP_IDB", "") == "1" and not force_idb:
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
        has_ref = any(
            r.get("value", {}).get("stsTokenManager", {}).get("refreshToken")
            for r in idb if isinstance(r.get("value"), dict))
        # Don't clobber a good on-disk refresh_token with empty extract
        # (SPA often holds the DB open → evaluate returns []).
        if (not idb or not has_ref) and (sdir / "indexeddb.json").exists():
            try:
                prev = json.loads((sdir / "indexeddb.json").read_text())
                prev_ref = any(
                    r.get("value", {}).get("stsTokenManager", {}).get("refreshToken")
                    for r in prev if isinstance(r.get("value"), dict))
                if prev_ref and not has_ref:
                    log("  IndexedDB extract empty/missing RT — keeping existing indexeddb.json")
                    return
            except Exception:
                pass
        with open(sdir / "indexeddb.json", "w") as f:
            json.dump(idb, f, indent=2)
        log(f"  Saved {len(idb)} IndexedDB records, refresh_token={'YES' if has_ref else 'MISSING'}")
    except asyncio.TimeoutError:
        log("  IndexedDB save timed out — continuing with cookies+localStorage")
    except Exception as e:
        log(f"  IndexedDB save failed: {e}")


async def restore_firebase_idb(page, session_id) -> bool:
    """Inject disk indexeddb.json into the page. Ignores CHIMERA_SKIP_IDB.

    Needed on auth-wall revive: lean_sup sets SKIP_IDB so hydrate never loads
    the Firebase refresh_token into Chromium.
    """
    idb_file = _sess_dir(session_id) / "indexeddb.json"
    if not idb_file.exists():
        log("  No indexeddb.json on disk — cannot restore Firebase IDB")
        return False
    try:
        idb_data = json.loads(idb_file.read_text())
    except Exception as e:
        log(f"  indexeddb.json read failed: {e}")
        return False
    if not idb_data:
        log("  indexeddb.json empty")
        return False
    has_ref = any(
        isinstance(r.get("value"), dict)
        and (r["value"].get("stsTokenManager") or {}).get("refreshToken")
        for r in idb_data if isinstance(r, dict)
    )
    if not has_ref:
        log("  indexeddb.json has no refresh_token")
        return False
    # Synthesize Firebase fkey when extract saved key=null
    for r in idb_data:
        if not isinstance(r, dict):
            continue
        if r.get("key") or r.get("fkey"):
            continue
        v = r.get("value") if isinstance(r.get("value"), dict) else None
        if v and v.get("apiKey"):
            app = v.get("appName") or "[DEFAULT]"
            r["key"] = f"firebase:authUser:{v['apiKey']}:{app}"
            log("  synthesized IDB fkey from apiKey/appName")
    try:
        if "lovable.dev" not in ((page.url or "").lower()):
            try:
                await page.goto(
                    "https://lovable.dev/dashboard",
                    timeout=25000,
                    wait_until="commit",
                )
                await asyncio.sleep(2)
            except Exception as e:
                log(f"  IDB restore nav soft-fail: {type(e).__name__}")
        # Put-only (no deleteDatabase — hangs onblocked). Wait for tx.oncomplete.
        n = await asyncio.wait_for(
            page.evaluate(
                """(records) => new Promise((resolve) => {
                    const done = (v) => { try { resolve(v); } catch (e) {} };
                    const t = setTimeout(() => done(-2), 10000);
                    try {
                        const openReq = indexedDB.open('firebaseLocalStorageDb');
                        openReq.onupgradeneeded = () => {
                            try {
                                const db = openReq.result;
                                if (!db.objectStoreNames.contains('firebaseLocalStorage')) {
                                    db.createObjectStore('firebaseLocalStorage', {keyPath: 'fkey'});
                                }
                            } catch (e) {}
                        };
                        openReq.onerror = () => { clearTimeout(t); done(-1); };
                        openReq.onsuccess = () => {
                            try {
                                let db = openReq.result;
                                const write = (adb) => {
                                    try {
                                        if (!adb.objectStoreNames.contains('firebaseLocalStorage')) {
                                            clearTimeout(t); done(-1); return;
                                        }
                                        const tx = adb.transaction('firebaseLocalStorage', 'readwrite');
                                        const store = tx.objectStore('firebaseLocalStorage');
                                        let finished = 0;
                                        let putErr = false;
                                        if (!records.length) { clearTimeout(t); done(0); return; }
                                        tx.oncomplete = () => { clearTimeout(t); done(putErr ? -1 : finished); };
                                        tx.onerror = () => { clearTimeout(t); done(-1); };
                                        tx.onabort = () => { clearTimeout(t); done(-1); };
                                        records.forEach(r => {
                                            try {
                                                const putReq = store.put({
                                                    fkey: r.key || r.fkey,
                                                    value: r.value
                                                });
                                                putReq.onsuccess = () => { finished++; };
                                                putReq.onerror = () => { putErr = true; finished++; };
                                            } catch (e) { putErr = true; finished++; }
                                        });
                                    } catch (e) { clearTimeout(t); done(-1); }
                                };
                                if (!db.objectStoreNames.contains('firebaseLocalStorage')) {
                                    const v = db.version + 1;
                                    db.close();
                                    const open2 = indexedDB.open('firebaseLocalStorageDb', v);
                                    open2.onupgradeneeded = () => {
                                        try {
                                            open2.result.createObjectStore(
                                                'firebaseLocalStorage', {keyPath: 'fkey'});
                                        } catch (e) {}
                                    };
                                    open2.onerror = () => { clearTimeout(t); done(-1); };
                                    open2.onsuccess = () => write(open2.result);
                                    return;
                                }
                                write(db);
                            } catch (e) { clearTimeout(t); done(-1); }
                        };
                    } catch (e) { clearTimeout(t); done(-1); }
                })""",
                idb_data,
            ),
            timeout=12,
        )
        log(f"  Restored Firebase IDB for refresh (n={n}, refresh_token=YES)")
        return isinstance(n, int) and n > 0
    except asyncio.TimeoutError:
        log("  Firebase IDB restore timed out")
        return False
    except Exception as e:
        log(f"  Firebase IDB restore failed: {e}")
        return False


async def revive_via_refresh_token(page, session_id, *, target_url: str | None = None) -> bool:
    """Auth revive without password: disk refresh_token → new access token → cookies.

    Lovable's SPA keeps firebaseLocalStorageDb open, so page.evaluate IDB puts hang.
    Working path: mint token via Google API in Python, inject via add_init_script
    (runs before SPA), then navigate.
    """
    import time as _time
    import urllib.parse
    import urllib.request

    log("  Auth revive: refresh_token path (no password login)")
    idb_file = _sess_dir(session_id) / "indexeddb.json"
    if not idb_file.exists():
        log("  No indexeddb.json — cannot refresh")
        return False
    try:
        idb_data = json.loads(idb_file.read_text())
    except Exception as e:
        log(f"  indexeddb.json read failed: {e}")
        return False
    # synthesize null keys
    for r in idb_data:
        if not isinstance(r, dict):
            continue
        if r.get("key") or r.get("fkey"):
            continue
        v = r.get("value") if isinstance(r.get("value"), dict) else None
        if v and v.get("apiKey"):
            r["key"] = f"firebase:authUser:{v['apiKey']}:{v.get('appName') or '[DEFAULT]'}"
    user = None
    for r in idb_data:
        v = r.get("value") if isinstance(r, dict) else None
        if isinstance(v, dict) and (v.get("stsTokenManager") or {}).get("refreshToken"):
            user = v
            break
    if not user:
        log("  indexeddb.json has no refresh_token")
        return False
    stm = user["stsTokenManager"]
    api_key = user.get("apiKey") or ""
    # Mint new access token outside the page (avoids IDB lock + CDP hangs)
    try:
        body = urllib.parse.urlencode(
            {"grant_type": "refresh_token", "refresh_token": stm["refreshToken"]}
        ).encode()
        req = urllib.request.Request(
            f"https://securetoken.googleapis.com/v1/token?key={api_key}",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            tok = json.loads(resp.read().decode())
        if not tok.get("access_token"):
            log(f"  Google refresh failed: {str(tok)[:180]}")
            return False
        stm["accessToken"] = tok["access_token"]
        stm["expirationTime"] = int(_time.time() * 1000) + int(
            tok.get("expires_in", 3600)
        ) * 1000
        if tok.get("refresh_token"):
            stm["refreshToken"] = tok["refresh_token"]
        log("  Google refresh_token → new access_token OK")
    except Exception as e:
        log(f"  Google refresh error: {e}")
        return False
    # Persist updated tokens to disk before inject
    try:
        idb_file.write_text(json.dumps(idb_data, indent=2))
    except Exception:
        pass
    # Init-script inject BEFORE Lovable SPA opens the DB
    init_js = (
        "(() => {\n"
        f"  const records = {json.dumps(idb_data)};\n"
        "  window.__chimeraIdbReady = new Promise((resolve) => {\n"
        "    try {\n"
        "      const openReq = indexedDB.open('firebaseLocalStorageDb');\n"
        "      openReq.onupgradeneeded = () => {\n"
        "        try {\n"
        "          const db = openReq.result;\n"
        "          if (!db.objectStoreNames.contains('firebaseLocalStorage'))\n"
        "            db.createObjectStore('firebaseLocalStorage', {keyPath: 'fkey'});\n"
        "        } catch (e) {}\n"
        "      };\n"
        "      openReq.onerror = () => resolve(false);\n"
        "      openReq.onsuccess = () => {\n"
        "        try {\n"
        "          const db = openReq.result;\n"
        "          if (!db.objectStoreNames.contains('firebaseLocalStorage')) {\n"
        "            resolve(false); return;\n"
        "          }\n"
        "          const tx = db.transaction('firebaseLocalStorage', 'readwrite');\n"
        "          const store = tx.objectStore('firebaseLocalStorage');\n"
        "          records.forEach(r => {\n"
        "            try { store.put({fkey: r.key || r.fkey, value: r.value}); } catch (e) {}\n"
        "          });\n"
        "          tx.oncomplete = () => resolve(true);\n"
        "          tx.onerror = () => resolve(false);\n"
        "        } catch (e) { resolve(false); }\n"
        "      };\n"
        "    } catch (e) { resolve(false); }\n"
        "  });\n"
        "})();"
    )
    dest = target_url or "https://lovable.dev/dashboard"
    # CRITICAL: reuse of a context that already loaded lovable.dev leaves a
    # half-init Firebase IDB; virgin context + init_script is the proven path.
    browser = page.context.browser
    if browser is None:
        log("  No browser handle for virgin context")
        return False
    fresh_ctx = None
    try:
        fresh_ctx = await browser.new_context()
        await fresh_ctx.add_init_script(init_js)
        fresh = await fresh_ctx.new_page()
        await fresh.goto(dest, timeout=40000, wait_until="domcontentloaded")
        try:
            ready = await asyncio.wait_for(
                fresh.evaluate("() => window.__chimeraIdbReady"),
                timeout=8,
            )
            log(f"  IDB init inject ready={ready}")
        except Exception as e:
            log(f"  IDB init wait soft-fail: {type(e).__name__}")
        await asyncio.sleep(4)
        if await detect_auth_wall(fresh):
            try:
                await fresh.reload(timeout=40000, wait_until="domcontentloaded")
                await asyncio.sleep(4)
            except Exception:
                pass
        if await detect_auth_wall(fresh):
            log("  Refresh ran but still on auth wall")
            return False
        cookies = await fresh_ctx.cookies()
        sdir = _sess_dir(session_id)
        with open(sdir / "cookies.json", "w") as f:
            json.dump(cookies, f, indent=2)
        log(f"  Auth revived via refresh_token — saved {len(cookies)} cookies")
        # Apply into the caller's context and navigate
        try:
            await page.context.clear_cookies()
        except Exception:
            pass
        try:
            await page.context.add_cookies(cookies)
        except Exception as e:
            log(f"  cookie copy soft-fail: {e}")
        try:
            await page.goto(dest, timeout=40000, wait_until="domcontentloaded")
            await asyncio.sleep(3)
        except Exception as e:
            log(f"  caller goto soft-fail: {type(e).__name__}")
        return True
    except Exception as e:
        log(f"  virgin-context revive failed: {type(e).__name__}: {e}")
        return False
    finally:
        if fresh_ctx is not None:
            try:
                await fresh_ctx.close()
            except Exception:
                pass


async def ensure_authed(
    page,
    session_id,
    config: dict | None,
    *,
    target_url: str | None = None,
    allow_password_login: bool = True,
) -> bool:
    """Clear auth wall: refresh_token first, password login only as last resort."""
    try:
        walled = await detect_auth_wall(page)
    except Exception:
        walled = True
    if not walled:
        return True
    if session_id and await revive_via_refresh_token(
        page, session_id, target_url=target_url
    ):
        return True
    if not allow_password_login:
        log("  Refresh failed — password login disabled")
        return False
    if not config:
        log("  Refresh failed — no config for password login")
        return False
    log("  Refresh failed/unavailable — falling back to do_login")
    ok = await do_login(
        page,
        config.get("email", ""),
        config.get("password", ""),
        config.get("totp_secret"),
    )
    if ok and session_id:
        try:
            await save_trio(page.context, page, session_id, force_idb=True)
        except Exception:
            pass
        if target_url:
            try:
                await page.goto(target_url, timeout=25000, wait_until="commit")
                await asyncio.sleep(3)
            except Exception:
                pass
    return bool(ok)


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
    if "request access" in bl and ("log in" in bl or "switch to an account" in bl):
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
    await asyncio.sleep(3)

    if "/dashboard" in page.url or "/projects" in page.url:
        log("  Already logged in")
        return True

    try:
        await page.locator('input[placeholder="Email"]').fill(email)
        await page.locator('[data-testid="auth-submit-button"]').click()
        await asyncio.sleep(3)
    except Exception as e:
        log(f"  Email step failed: {e}")
        return False

    try:
        await page.locator('input[placeholder="Password"]').fill(password)
        await page.locator('[data-testid="auth-submit-button"]').click()
        await asyncio.sleep(6)
    except Exception as e:
        log(f"  Password step failed: {e}")
        return False

    try:
        body = await asyncio.wait_for(
            page.evaluate("() => document.body.innerText.slice(0, 500)"),
            timeout=8,
        )
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
            await asyncio.sleep(1)
            await page.get_by_role("button", name="Verify").click(timeout=5000)
            await asyncio.sleep(6)
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
    """True when Playwright page/browser is dead — fresh tab / relaunch."""
    s = str(exc).lower()
    needles = (
        "target closed",
        "target crashed",
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
        "aw, snap",
        "page crashed",
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


async def _shutdown_browser(pw, browser) -> None:
    """Close browser + Playwright driver with hard timeouts (driver may be dead)."""
    if browser is not None:
        try:
            await asyncio.wait_for(browser.close(), timeout=15)
        except Exception:
            pass
    if pw is not None:
        try:
            await asyncio.wait_for(pw.stop(), timeout=15)
        except Exception:
            pass


async def capture_debug(chat_page, preview_page, tag: str,
                        xvfb_only: bool = False) -> None:
    """Playwright page shots + Xvfb root shot so we can see headed :99 state.

    xvfb_only skips page.screenshot — those go through CDP and time out /
    add load on a busy renderer; the Xvfb grab is an external process.
    """
    try:
        SHOT_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        log(f"  Shot dir fail: {e}")
        return
    stamp = time.strftime("%H%M%S")
    pages = [] if xvfb_only else [(chat_page, "chat")]
    if (not xvfb_only and preview_page is not None
            and preview_page is not chat_page):
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


async def run_daemon(session_id, project_id, browser_type, threads, mode, headed=False):
    from playwright.async_api import async_playwright
    from miner_injector import inject_miner

    config = load_config_sync(session_id)
    log(f"Session: {session_id} ({config.get('email', '?')})")
    log(f"Project: {project_id}")
    log(f"Browser: {browser_type} headed={headed}")
    log("Forever mode: one browser kept up; issues handled in place, fresh tab only if a tab wedges")

    preview_url = f"https://{project_id}.lovableproject.com"
    chat_url = f"https://lovable.dev/projects/{project_id}"

    cycle = 0
    reconnect_streak = 0
    force_hard_kill = False
    tab_fail_streak = 0  # fresh tabs in a row that never reached the health loop
    # One Playwright + one browser kept across cycles. A "cycle" is a fresh tab
    # in the same browser; the browser is only relaunched if its process died.
    pw = None
    browser = None
    context = None
    while True:
        cycle += 1
        attached = False
        exit_mode = "tab"
        reached_health = False
        browser_up = False
        force_hard_kill = False
        try:
            browser_up = browser is not None and browser.is_connected()
        except Exception:
            browser_up = False
        need_new_browser = (not browser_up
                            or tab_fail_streak >= TAB_FAILS_BEFORE_BROWSER)
        log(f"=== Cycle #{cycle} — "
            f"{'launch browser' if need_new_browser else 'same browser, fresh tab'} "
            f"(tab_fail_streak={tab_fail_streak}) ===")
        try:
            if need_new_browser:
                if browser_up:
                    log(f"  {tab_fail_streak} fresh tabs never came up — "
                        f"relaunching browser (last resort)")
                await _shutdown_browser(pw, browser)
                pw = browser = context = None
                tab_fail_streak = 0
                # Always reap zombies + clear any leftover Chrome before launch
                kill_browser_orphans()
                if cdp_http_alive():
                    hard_kill_chrome()
                reclaim_if_pressure("pre-launch")

                pw = await async_playwright().start()
                if browser_type == "chromium":
                    # 1GB Railway: headed Xvfb OOMs (Aw Snap #5). Prefer headless
                    # when cgroup ≤1.1GB unless CHIMERA_FORCE_HEADED=1.
                    mem_gb = cgroup_mem_gb()
                    use_headed = headed
                    force_headed = os.environ.get("CHIMERA_FORCE_HEADED", "") == "1"
                    disp = (os.environ.get("DISPLAY") or "").strip()
                    # Empty Xvfb was caused by auto-headless on 1GB while DISPLAY=:99
                    # was set but CHIMERA_FORCE_HEADED missing (cell-16 lean_sup).
                    if mem_gb and mem_gb <= 1.15 and not force_headed:
                        if disp:
                            log(f"  cgroup {mem_gb:.2f}GB ≤1.1 but DISPLAY={disp} "
                                f"— keeping headed (set CHIMERA_FORCE_HEADED=0 + "
                                f"unset DISPLAY to allow headless)")
                        else:
                            use_headed = False
                            log(f"  cgroup {mem_gb:.2f}GB ≤1.1 — forcing headless "
                                f"(set CHIMERA_FORCE_HEADED=1 to override)")
                    chrome_args = _chromium_lean_args()
                    if use_headed:
                        # Force real X11 windows on Xvfb (else ozone can stay blank)
                        chrome_args = list(chrome_args) + [
                            "--ozone-platform=x11",
                            "--ozone-platform-hint=x11",
                        ]
                    browser = await pw.chromium.launch(
                        headless=not use_headed, args=chrome_args)
                    log("  Launched Chromium via Playwright "
                        f"(headless={not use_headed}, DISPLAY={disp or '-'}, "
                        f"1GB max-strip flags)")
                else:
                    browser = await pw.firefox.launch(headless=not headed)
                    log("  Launched Firefox via Playwright")
                # Match Chrome --window-size + Xvfb (Lovable needs room for Preview)
                _vp = {"width": VIEW_W, "height": VIEW_H}
                context = await browser.new_context(
                    viewport=_vp,
                    user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"))
                await install_memory_guards(context)
                await install_focus_spoof(context)

            old_pages = []
            try:
                old_pages = list(context.pages)
            except Exception:
                old_pages = []
            # Cookies BEFORE first nav — required when we skip post-LS reload on 1GB
            try:
                cookies = load_cookies_sync(session_id)
                await asyncio.wait_for(context.add_cookies(cookies), timeout=10)
                log(f"Loaded {len(cookies)} cookies (pre-nav)")
            except Exception as e:
                log(f"  Cookie load soft-fail: {e}")
            # LS via init script (before SPA) — avoids page.evaluate Aw Snap on 1GB
            # Arm once per context (fresh-tab cycles reuse context).
            _sdir_early = _sess_dir(session_id)
            _ls_early = _sdir_early / "localstorage.json"
            if _ls_early.exists() and not getattr(context, "_chimera_ls_init", False):
                try:
                    with open(_ls_early) as f:
                        _ls_data = json.load(f)
                    _payload = json.dumps(_ls_data)
                    await context.add_init_script(
                        f"""(() => {{
                          try {{
                            const data = {_payload};
                            for (const [k, v] of Object.entries(data)) {{
                              try {{
                                localStorage.setItem(
                                  k, (typeof v === 'string') ? v : JSON.stringify(v));
                              }} catch (e) {{}}
                            }}
                          }} catch (e) {{}}
                        }})();"""
                    )
                    context._chimera_ls_init = True
                    log(f"  LS init-script armed ({len(_ls_data)} keys) — applies on goto")
                except Exception as e:
                    log(f"  LS init-script soft-fail: {type(e).__name__}: {e}")
            chat_page = await context.new_page()
            for op in old_pages:
                try:
                    await asyncio.wait_for(op.close(), timeout=8)
                except Exception:
                    pass
            if old_pages:
                log(f"  Opened fresh tab, closed {len(old_pages)} old tab(s) — browser stays up")
            log(f"Opening chat: {chat_url}")
            goto_ok = await safe_goto(chat_page, chat_url, timeout_s=25)
            if not goto_ok:
                log("  goto soft-fail — will recover")
                ok, chat_page = await recover_aw_snap(
                    chat_page, chat_url, tag="open", context=context)
                if not ok:
                    tab_fail_streak = TAB_FAILS_BEFORE_BROWSER
                    raise RuntimeError("aw-snap-on-open")
            else:
                # Skip recover/focus after successful goto — those CDP calls
                # freeze the asyncio loop on Railway 1GB after commit.
                log("  open: goto ok — skip aw-snap recover/focus")

            # Check if logged in — URL alone misses "You don't have access"
            # (still on /projects/… with a private-project modal).
            try:
                cur_url = chat_page.url or ""
            except Exception:
                cur_url = ""
            need_auth = "/login" in cur_url or "/auth" in cur_url
            if not need_auth:
                try:
                    need_auth = await detect_auth_wall(chat_page)
                except Exception:
                    need_auth = False
            if need_auth:
                log("Auth wall on open — refresh_token first (then login if needed)")
                ok = await ensure_authed(
                    chat_page,
                    session_id,
                    config,
                    target_url=chat_url,
                )
                if not ok:
                    log("Auth revive failed — retrying in 5 min...")
                    raise RuntimeError("login-failed-retry")
                try:
                    await safe_goto(chat_page, chat_url, timeout_s=25)
                except Exception:
                    pass
                log("  post-auth-revive: skip aw-snap recover")

            # --- Step 2: Restore localStorage + IndexedDB ---
            sdir = _sess_dir(session_id)
            low_mem_hydrate = bool(cgroup_mem_gb() and cgroup_mem_gb() <= 1.15)
            # Restore on chat page (lovable.dev domain)
            ls_file = sdir / "localstorage.json"
            if low_mem_hydrate:
                log("  Skip LS page.evaluate on 1GB — init-script already applied pre-nav")
            elif ls_file.exists():
                try:
                    with open(ls_file) as f:
                        ls_data = json.load(f)
                    # Thread watchdog — evaluate can freeze the asyncio loop.
                    import threading as _th
                    _stop = _th.Event()
                    def _wd():
                        if not _stop.wait(12):
                            log("  LS restore watchdog — hard_kill")
                            try:
                                hard_kill_chrome()
                            except Exception:
                                pass
                    _th.Thread(target=_wd, daemon=True).start()
                    try:
                        await asyncio.wait_for(
                            chat_page.evaluate(
                                "(data) => { for (const [k, v] of Object.entries(data)) "
                                "{ try { localStorage.setItem(k, v); } catch(e) {} } }",
                                ls_data),
                            timeout=10,
                        )
                        log(f"Restored {len(ls_data)} localStorage keys")
                    finally:
                        _stop.set()
                except Exception as e:
                    log(f"localStorage restore failed: {type(e).__name__}: {e}")

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

            # Cookies + LS ideally stick after reload — but on ~1GB Railway the
            # post-LS reload Aw-Snaps the renderer (Target crashed ×15). Prefer
            # cookies-before-nav when possible; skip reload on low-mem.
            if low_mem_hydrate:
                log("  Skip post-LS reload on 1GB — init-script LS + cookies pre-nav")
                await asyncio.sleep(8)  # let SPA hydrate before composer probe
            else:
                log("  Reloading chat so cookies/LS apply…")
                if not await safe_goto(chat_page, chat_url, timeout_s=25):
                    log("  post-LS reload soft-fail — continuing")
                await asyncio.sleep(5)
            log("  hydrate: skip aw-snap recover (1GB path)")

            # Cookie/auth: URL-only misses private-project wall on /projects/…
            try:
                cur_url = chat_page.url or ""
            except Exception:
                cur_url = ""
            need_auth = "/login" in cur_url or "/auth" in cur_url
            if not need_auth:
                try:
                    need_auth = await detect_auth_wall(chat_page)
                except Exception:
                    need_auth = False
            if need_auth:
                log("  Auth wall after restore — refresh_token first")
                logged = await ensure_authed(
                    chat_page,
                    session_id,
                    config,
                    target_url=chat_url,
                )
                if not logged:
                    log("  Auth revive failed — fresh tab")
                    force_hard_kill = True
                    raise RuntimeError("cycle-restart")
                await safe_goto(chat_page, chat_url, timeout_s=25)
                log("  Auth wall cleared — continuing")
            else:
                log("  post-hydrate: no auth wall")

            await asyncio.sleep(4)
            # Do NOT probe preview frames before composer — cold shell_worker_status
            # wedges CDP while the SPA is still hydrating (Xvfb looks fine, evaluate hangs).
            preview_page = chat_page
            injected = False
            alive0, det0 = False, "deferred"

            import random as _rand
            import threading as _th
            chat_input = None
            cdp_hung_streak = 0
            low_mem = bool(cgroup_mem_gb() and cgroup_mem_gb() <= 1.15)
            if not injected:
              for round_n in range(1, COMPOSER_TRIES + 1):
                _stop = _th.Event()
                def _cwd(_s=_stop, _r=round_n):
                    if not _s.wait(40):
                        log(f"  composer-r{_r} watchdog — hard_kill")
                        try:
                            hard_kill_chrome()
                        except Exception:
                            pass
                _th.Thread(target=_cwd, daemon=True).start()
                try:
                    try:
                        cur = chat_page.url or ""
                    except Exception:
                        cur = ""
                    mid_wall = "/login" in cur or "/auth" in cur
                    if not mid_wall:
                        try:
                            mid_wall = await detect_auth_wall(chat_page)
                        except Exception:
                            mid_wall = False
                    if mid_wall:
                        log(f"  Auth wall mid composer hunt (r{round_n}) — refresh_token first")
                        logged = await ensure_authed(
                            chat_page,
                            session_id,
                            config,
                            target_url=chat_url,
                        )
                        if logged:
                            await safe_goto(chat_page, chat_url, timeout_s=25)
                        else:
                            force_hard_kill = True
                            raise RuntimeError("cycle-restart")
                    if not low_mem:
                        await light_focus(chat_page)
                    chat_input, cdp_hung = await find_chat_composer(
                        chat_page, tag=f"start-r{round_n}")
                    if chat_input:
                        log(f"Chat input found (round {round_n}/{COMPOSER_TRIES})")
                        break
                    if cdp_hung:
                        cdp_hung_streak += 1
                        # Target crashed / Aw Snap: one hit is enough — do not
                        # burn COMPOSER_TRIES × 10s on a dead renderer.
                        try:
                            dead_tab = await page_is_aw_snap(chat_page)
                        except Exception:
                            dead_tab = True
                        need = 1 if (dead_tab or low_mem) else 3
                        log(f"CDP slow/dead on composer (round {round_n}, "
                            f"streak={cdp_hung_streak}/{need}"
                            f"{', tab-dead' if dead_tab else ''})")
                        if cdp_hung_streak >= need:
                            log("Composer hunt: dead tab — HARD kill + relaunch (1GB)")
                            try:
                                hard_kill_chrome()
                            except Exception:
                                pass
                            force_hard_kill = True
                            raise RuntimeError("aw-snap-relaunch")
                    else:
                        cdp_hung_streak = 0
                    log(f"Chat input missing (round {round_n}/{COMPOSER_TRIES}) — wait {COMPOSER_WAIT_S}s (no reload)")
                    # After a few empty hunts on 1GB, force login — cookies/LS
                    # may look "logged in" by URL while UI is access-walled.
                    if low_mem and round_n in (3, 8):
                        log(f"  Composer still missing r{round_n} — try refresh_token")
                        try:
                            logged = await ensure_authed(
                                chat_page,
                                session_id,
                                config,
                                target_url=chat_url,
                            )
                            if logged:
                                await safe_goto(chat_page, chat_url, timeout_s=25)
                                await asyncio.sleep(5)
                        except Exception as e:
                            log(f"  mid-hunt auth revive skip: {type(e).__name__}")
                    await asyncio.sleep(COMPOSER_WAIT_S)
                finally:
                    _stop.set()

              if not chat_input:
                log("Chat input not found — fresh tab (browser stays up)")
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

              # --- Step 4: keep prompting + remounting until lovableproject
              # iframe has window.doc('nproc'), then inject (or DOC_MARK exit)
              preview_page = chat_page
              injected = False
              doc_mark = os.environ.get("CHIMERA_DOC_MARK", "") == "1"
              mark_rounds = int(os.environ.get("CHIMERA_DOC_MARK_ROUNDS", "6"))
              log("  After wake — looking for lovableproject iframe + doc('nproc')...")
              if doc_mark:
                  log(f"  CHIMERA_DOC_MARK=1 — max_rounds={mark_rounds}, stop after verdict")
              # Mining: wait for lovableproject sandbox/doc. Blank white Preview
              # soft-reloads chat every BLANK_PREVIEW_RELOAD_ROUNDS, then
              # hard-kills browser at BLANK_PREVIEW_HARD_ROUNDS (no wedge).
              sandbox_in_chat = await bring_up_lovableproject_doc(
                  chat_page,
                  max_rounds=(mark_rounds if doc_mark else 0),
                  wait_per_round_s=75,
                  project_id=project_id,
                  session_id=session_id,
                  session_config=config,
                  chat_url=chat_url)

              if doc_mark:
                  mark_path = Path("/app/work/DOC_MARK.txt")
                  if sandbox_in_chat:
                      log("DOC_MARK=OK — doc('nproc') works on lovableproject")
                      try:
                          mark_path.write_text("OK\n")
                      except Exception:
                          pass
                  else:
                      log("DOC_MARK=NOT_RUNNING — doc('nproc') failed / no bridge")
                      try:
                          mark_path.write_text("NOT_RUNNING\n")
                      except Exception:
                          pass
                  log("DOC_MARK done — exiting (no inject / no health loop)")
                  try:
                      await browser.close()
                  except Exception:
                      pass
                  try:
                      await pw.stop()
                  except Exception:
                      pass
                  return

              if sandbox_in_chat:
                  for inj_try in range(1, 4):
                      log(f"Injecting worker via lovableproject iframe (try {inj_try}/3)...")
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
                      log("  Inject missed — re-prompt + look for lovableproject again")
                      try:
                          await asyncio.wait_for(
                              send_presence_prompt(chat_page), timeout=40)
                      except Exception as e:
                          log(f"  Retry presence skip: {type(e).__name__}")
                      await bring_up_lovableproject_doc(
                          chat_page, max_rounds=2, wait_per_round_s=60,
                          project_id=project_id,
                          session_id=session_id,
                          session_config=config,
                          chat_url=chat_url)
              else:
                  log("  Page died before lovableproject+doc — health/fresh tab will retry")

              if not injected:
                  log("  Worker not injected yet — health loop will keep looking")

            if injected:
                log("Worker injected!" if not alive0 else "Worker already running (reconnect)")
            else:
                log("Worker injection returned False — health loop will retry")

            # Save state from chat origin (Firebase LS/IDB live on lovable.dev,
            # not the preview sandbox — saving from preview wipes the trio).
            # force_idb=True so we always pull refresh_token for next revive,
            # even when CHIMERA_SKIP_IDB=1 (hydrate still skipped on boot).
            try:
                await save_trio(context, chat_page, session_id, force_idb=True)
            except Exception as e:
                log(f"save_trio error (continuing): {e}")

            if mode != "full":
                log(f"Mode={mode} — inject done, exiting (no health loop)")
                await browser.close()
                await pw.stop()
                return

            # Full mode: forever health on this tab — issues handled in place,
            # no reloads, browser never killed from here.
            log("Starting health check loop (full mode)...")
            reached_health = True
            tab_fail_streak = 0
            last_refresh = time.time()
            page_lock = asyncio.Lock()  # serialize revive vs token refresh
            # CRITICAL+nodoc Force-/term failures before hard-kill self-heal.
            crit_term_miss = 0

            async def daemon_health_loop():
                """Shell/worker dead → soft confirm → reinject in place (no reload).

                Babysit Chromium on 1GB: under mem pressure skip chat prompts /
                CDP-heavy pokes and widen the gap so we don't Aw Snap ourselves.
                """
                nonlocal exit_mode, reconnect_streak, crit_term_miss
                iteration = 0
                fail_streak = 0
                soft_dead = 0
                while True:
                    iteration += 1
                    log(f"Health check #{iteration}...")
                    next_wait = HEALTH_INTERVAL_S
                    tier = mem_pressure_tier()
                    frac = cgroup_mem_used_frac()

                    # Browser/page gone → kill zombies, relaunch (not soft reconnect)
                    if not await _browser_alive(browser, chat_page, preview_page):
                        try:
                            hard_kill_chrome()
                        except Exception:
                            pass
                        exit_mode = "kill"
                        log("  Browser/page closed — hard-kill + relaunch")
                        return

                    # Zombie reap; hard-kill only at absolute cgroup ceiling.
                    # Never hard-kill on health-1 (post-inject mem spike ≈100%).
                    if iteration == 1:
                        reclaim_if_pressure(
                            f"health-{iteration}", allow_hard_kill=False)
                    elif iteration % 5 == 0:
                        if reclaim_if_pressure(f"health-{iteration}"):
                            exit_mode = "kill"
                            log("  Cgroup ceiling reclaim — relaunch browser")
                            return

                    # --- Babysit tiers: cut CDP load before the renderer dies ---
                    if tier == "critical":
                        log(f"  Babysit CRITICAL mem={frac:.0%} — probe only, "
                            f"skip poke/prompt/shots")
                        next_wait = 80
                    else:
                        # Keep chat+preview warm (light poke when careful)
                        try:
                            await keep_pages_warm(
                                chat_page, preview_page,
                                light=(tier == "careful"))
                        except Exception as e_warm:
                            if _is_crash_error(e_warm) or not await _browser_alive(
                                    browser, chat_page, preview_page):
                                try:
                                    hard_kill_chrome()
                                except Exception:
                                    pass
                                exit_mode = "kill"
                                log("  Page dead on presence poke — hard-kill + relaunch")
                                return

                        if tier == "careful":
                            log(f"  Babysit careful mem={frac:.0%} — light poke, "
                                f"no chat prompt")
                            next_wait = 65
                            if not page_lock.locked():
                                try:
                                    await dismiss_blocking_popups(
                                        chat_page, max_passes=2)
                                except Exception:
                                    pass
                        else:
                            # Full presence: even ticks submit a trivial prompt,
                            # odd ticks type-without-submit (activity, zero credits)
                            if not page_lock.locked():
                                try:
                                    await dismiss_blocking_popups(
                                        chat_page, max_passes=5)
                                    if iteration % 2 == 0:
                                        await send_presence_prompt(chat_page)
                                    else:
                                        await type_idle_text(chat_page)
                                    await dismiss_blocking_popups(
                                        chat_page, max_passes=3)
                                except Exception as e_pp:
                                    if _is_crash_error(e_pp) or not await _browser_alive(
                                            browser, chat_page, preview_page):
                                        try:
                                            hard_kill_chrome()
                                        except Exception:
                                            pass
                                        exit_mode = "kill"
                                        log("  Page dead on presence prompt — "
                                            "hard-kill + relaunch")
                                        return
                                    log(f"  Presence prompt skip: {type(e_pp).__name__}")

                            # Xvfb shots rare — every 6th, never under careful/critical
                            if iteration == 1 or iteration % 6 == 0:
                                await capture_debug(
                                    chat_page, preview_page, f"h{iteration}",
                                    xvfb_only=True)

                    try:
                        alive, detail = await asyncio.wait_for(
                            shell_worker_status(preview_page), timeout=45)
                        if alive:
                            fail_streak = 0
                            soft_dead = 0
                            reconnect_streak = 0
                            crit_term_miss = 0
                            log(f"  Worker alive (probe: {detail}) — skip inject")
                            log("  Preview healthy")
                        else:
                            soft_dead += 1
                            # On 1GB headed, CRITICAL mem makes CDP falsely report
                            # nodoc/proxy-404; revive then wedges (cell-16/13).
                            # Demand more confirms + longer gap, then Force /term;
                            # miss×3 OR revive miss×CRIT_REVIVE_BOUNCE → auto bounce.
                            confirm_need = HEALTH_DEAD_CONFIRM
                            flake = (
                                detail == "nodoc"
                                or detail == "proxy-404"
                                or detail.startswith("proxy-404")
                                or detail.startswith("doc-eval-error")
                                or detail.startswith("probe-eval-error")
                                or detail.startswith("probe-error")
                                or detail.startswith("url-error")
                            )
                            if tier == "critical" and flake:
                                confirm_need = max(HEALTH_DEAD_CONFIRM, 4)
                                next_wait = max(HEALTH_DEAD_GAP_S, 35)
                            log(f"  Shell/worker soft-dead ({detail}) "
                                f"confirm {soft_dead}/{confirm_need}")
                            if tier == "critical" and flake:
                                log(f"  CRITICAL mem — soft-dead patience "
                                    f"{soft_dead}/{confirm_need} gap={next_wait}s")
                            if soft_dead < confirm_need:
                                if next_wait == HEALTH_INTERVAL_S:
                                    next_wait = HEALTH_DEAD_GAP_S
                                # Under CRITICAL+flake: remount Preview so CDP
                                # can see doc again — do not escalate yet.
                                if tier == "critical" and flake:
                                    try:
                                        await ensure_preview_shell_panel(chat_page)
                                    except Exception:
                                        pass
                                await asyncio.sleep(next_wait)
                                continue
                            soft_dead = 0
                            log(f"  Worker not running ({detail}) — inject/revive")
                            # Stale cookies → "You don't have access" with no Preview.
                            # Refresh before Force /term / revive.
                            try:
                                if detail in ("login", "auth-wall") or await detect_auth_wall(
                                        chat_page):
                                    log("  Soft-dead: access/login wall — refresh_token")
                                    revived = await ensure_authed(
                                        chat_page,
                                        session_id,
                                        config,
                                        target_url=chat_url,
                                    )
                                    if revived:
                                        try:
                                            await safe_goto(
                                                chat_page, chat_url, timeout_s=25)
                                        except Exception:
                                            pass
                            except Exception as e:
                                log(f"  Soft-dead auth check soft: {type(e).__name__}")
                            # CRITICAL 1GB flake: stay on tab, Force /term. If DOC
                            # returns → fall through to in-place inject. If Force
                            # /term keeps missing → hard-kill + relaunch (self-heal
                            # beats spinning forever on a dead id-preview tab).
                            if tier == "critical" and flake:
                                log("  CRITICAL mem — stay on tab (no fresh-tab); "
                                    f"force /term + remount ({detail})")
                                try:
                                    await ensure_preview_shell_panel(chat_page)
                                except Exception:
                                    pass
                                term_ok = False
                                try:
                                    term_ok = await force_preview_to_lovableproject_term(
                                        chat_page, project_id)
                                except Exception as e:
                                    log(f"  Force /term soft: {type(e).__name__}")
                                if term_ok:
                                    crit_term_miss = 0
                                    log("  CRITICAL mem — /term DOC back, "
                                        "in-place inject next")
                                    # fall through to revive_sandbox below
                                else:
                                    crit_term_miss += 1
                                    log(f"  CRITICAL mem — Force /term miss "
                                        f"{crit_term_miss}/3")
                                    if crit_term_miss >= 3:
                                        try:
                                            hard_kill_chrome()
                                        except Exception:
                                            pass
                                        exit_mode = "kill"
                                        log("  CRITICAL mem — Force /term stuck "
                                            "3x — hard-kill + relaunch (self-heal)")
                                        return
                                    next_wait = max(next_wait, 45)
                                    await asyncio.sleep(next_wait)
                                    continue
                            if tier == "critical":
                                # doc ok / worker-missing: in-place revive only
                                log("  CRITICAL mem — in-place revive "
                                    "(no fresh tab)")
                            await capture_debug(
                                chat_page, preview_page,
                                f"dead-{detail.replace('/', '-')[:40]}",
                                xvfb_only=True)
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
                                            session_id=session_id,
                                        ),
                                        timeout=(
                                            180 if tier == "critical"
                                            else REVIVE_WALL_S),
                                    )
                                if ok:
                                    fail_streak = 0
                                    crit_term_miss = 0
                                    try:
                                        # Always re-download refresh_token after revive
                                        await save_trio(
                                            context, chat_page, session_id,
                                            force_idb=True)
                                    except Exception:
                                        pass
                                    log("  Revive OK — worker running again")
                                else:
                                    fail_streak += 1
                                    log(f"  Revive missed (streak={fail_streak}) — retry next tick")
                                    next_wait = 30
                                    # Under CRITICAL: force /term, then auto-bounce
                                    # after CRIT_REVIVE_BOUNCE misses (no forever cap).
                                    if tier == "critical":
                                        try:
                                            await force_preview_to_lovableproject_term(
                                                chat_page, project_id)
                                        except Exception:
                                            pass
                                        if fail_streak >= CRIT_REVIVE_BOUNCE:
                                            try:
                                                hard_kill_chrome()
                                            except Exception:
                                                pass
                                            exit_mode = "kill"
                                            log(f"  CRITICAL revive miss "
                                                f"x{CRIT_REVIVE_BOUNCE} — "
                                                "hard-kill + relaunch (self-heal)")
                                            return
                                    elif fail_streak >= FAIL_STREAK_RESTART:
                                        exit_mode = (
                                            "reconnect" if cdp_http_alive() else "kill")
                                        log(f"  Revive missed {FAIL_STREAK_RESTART}x — fresh tab (browser stays up)")
                                        return
                            except asyncio.TimeoutError:
                                fail_streak += 1
                                log(f"  Revive timed out "
                                    f"{180 if tier == 'critical' else REVIVE_WALL_S}s "
                                    f"(streak={fail_streak})")
                                next_wait = 30
                                if tier == "critical":
                                    try:
                                        await force_preview_to_lovableproject_term(
                                            chat_page, project_id)
                                    except Exception:
                                        pass
                                    if fail_streak >= CRIT_REVIVE_BOUNCE:
                                        try:
                                            hard_kill_chrome()
                                        except Exception:
                                            pass
                                        exit_mode = "kill"
                                        log(f"  CRITICAL revive timeout "
                                            f"x{CRIT_REVIVE_BOUNCE} — "
                                            "hard-kill + relaunch (self-heal)")
                                        return
                                elif fail_streak >= FAIL_STREAK_RESTART:
                                    exit_mode = (
                                        "reconnect" if cdp_http_alive() else "kill")
                                    log(f"  Revive timeout x{FAIL_STREAK_RESTART} — fresh tab (browser stays up)")
                                    return
                            except Exception as e2:
                                fail_streak += 1
                                log(f"  Revive error: {e2} (streak={fail_streak})")
                                if _is_crash_error(e2) or not await _browser_alive(
                                        browser, chat_page, preview_page):
                                    try:
                                        hard_kill_chrome()
                                    except Exception:
                                        pass
                                    exit_mode = "kill"
                                    log("  Page crashed during revive — hard-kill + relaunch")
                                    return
                                next_wait = 30
                                if tier == "critical":
                                    if fail_streak >= CRIT_REVIVE_BOUNCE:
                                        try:
                                            hard_kill_chrome()
                                        except Exception:
                                            pass
                                        exit_mode = "kill"
                                        log(f"  CRITICAL revive error "
                                            f"x{CRIT_REVIVE_BOUNCE} — "
                                            "hard-kill + relaunch (self-heal)")
                                        return
                                elif fail_streak >= FAIL_STREAK_RESTART:
                                    exit_mode = (
                                        "reconnect" if cdp_http_alive() else "kill")
                                    return

                    except asyncio.TimeoutError:
                        fail_streak += 1
                        log(f"  Health probe timed out 45s (streak={fail_streak})")
                        next_wait = 30
                        if tier == "critical":
                            # Don't fresh-tab under CRITICAL (id-preview wedge).
                            # Remount /term; if probe spiral continues → relaunch.
                            try:
                                await ensure_preview_shell_panel(chat_page)
                            except Exception:
                                pass
                            try:
                                await force_preview_to_lovableproject_term(
                                    chat_page, project_id)
                            except Exception:
                                pass
                            if fail_streak >= FAIL_STREAK_RESTART:
                                try:
                                    hard_kill_chrome()
                                except Exception:
                                    pass
                                exit_mode = "kill"
                                log(f"  CRITICAL probe timeout x{FAIL_STREAK_RESTART} "
                                    "— hard-kill + relaunch (self-heal)")
                                return
                        elif fail_streak >= FAIL_STREAK_RESTART:
                            log(f"  Probe timed out {FAIL_STREAK_RESTART}x — tab wedged, "
                                f"fresh tab (browser stays up)")
                            return
                    except Exception as e:
                        log(f"  Health check error: {e}")
                        if _is_crash_error(e) or not await _browser_alive(
                                browser, chat_page, preview_page):
                            try:
                                hard_kill_chrome()
                            except Exception:
                                pass
                            exit_mode = "kill"
                            log("  Page crashed in health check — hard-kill + relaunch")
                            return
                        next_wait = 30
                        fail_streak += 1
                        if fail_streak >= FAIL_STREAK_RESTART:
                            exit_mode = "reconnect" if cdp_http_alive() else "kill"
                            log(f"  Health errors {FAIL_STREAK_RESTART}x — fresh tab (browser stays up)")
                            return

                    # Randomize human cadence 40–60s when on the normal path
                    if next_wait == HEALTH_INTERVAL_S:
                        import random as _rh
                        next_wait = _rh.randint(
                            HEALTH_INTERVAL_S, HEALTH_INTERVAL_MAX_S)
                    log(f"  Next check in {next_wait}s...")
                    await asyncio.sleep(next_wait)

            health_task = asyncio.create_task(daemon_health_loop())

            # Token refresh — never overlap with revive (same chat page)
            while not health_task.done():
                await asyncio.sleep(60)
                if not await _browser_alive(browser, chat_page, preview_page):
                    try:
                        hard_kill_chrome()
                    except Exception:
                        pass
                    exit_mode = "kill"
                    log("Browser died during token loop — hard-kill + relaunch")
                    break
                now = time.time()
                if now - last_refresh >= TOKEN_REFRESH_INTERVAL:
                    if page_lock.locked():
                        log("--- TOKEN REFRESH skipped (revive in progress) ---")
                        continue
                    log("--- TOKEN REFRESH ---")
                    try:
                        async with page_lock:
                            # SKIP_IDB hydrate means Chromium may lack refresh_token —
                            # reinject from disk before minting a new access token.
                            tok_ok = await refresh_firebase_token(chat_page)
                            if not tok_ok:
                                log("  no live token — restore IDB from disk + retry")
                                if await restore_firebase_idb(chat_page, session_id):
                                    tok_ok = await refresh_firebase_token(chat_page)
                            if tok_ok:
                                await save_trio(
                                    context, chat_page, session_id, force_idb=True)
                    except Exception as e:
                        log(f"Token refresh error: {e}")
                        if _is_crash_error(e):
                            try:
                                hard_kill_chrome()
                            except Exception:
                                pass
                            exit_mode = "kill"
                            break
                    last_refresh = now

            # Drain health task if still running
            if not health_task.done():
                health_task.cancel()
                try:
                    await health_task
                except Exception:
                    pass

            if exit_mode == "kill":
                log("Health exited kill — hard-kill + full browser relaunch")
                try:
                    hard_kill_chrome()
                except Exception:
                    pass
                raise RuntimeError("aw-snap-relaunch")

            log("Tab handed back — fresh tab in same browser...")
            raise RuntimeError("tab-restart")

        except Exception as e:
            msg = str(e).strip()
            crashy = (
                force_hard_kill
                or msg.startswith("aw-snap")
                or msg == "aw-snap-relaunch"
                or _is_crash_error(e)
            )
            if crashy:
                log(f"  Crash/Aw Snap — hard-kill Chrome + zombies, relaunch ({msg})")
                try:
                    hard_kill_chrome()
                except Exception:
                    pass
                try:
                    await _shutdown_browser(pw, browser)
                except Exception:
                    pass
                pw = browser = context = None
                tab_fail_streak = TAB_FAILS_BEFORE_BROWSER
                force_hard_kill = False
                wait_s = 8
            elif msg == "login-failed-retry":
                wait_s = 300
            elif msg in (
                    "tab-restart", "cycle-restart", "cdp-reconnect",
                    "sandbox-never-ready"):
                wait_s = 5
                log(f"  soft-restart: {msg}")
                # Soft tab restart: reap zombies only — never SIGKILL live Chrome
                try:
                    reap_zombies_only()
                except Exception:
                    pass
            else:
                log(f"Handled error (same browser): {type(e).__name__}: {e}")
                traceback.print_exc()
                wait_s = 10
                try:
                    reap_zombies_only()
                except Exception:
                    pass
            if not reached_health and not crashy:
                tab_fail_streak += 1
            try:
                still_up = browser is not None and browser.is_connected()
            except Exception:
                still_up = False
            log(f"Continuing in {wait_s}s — "
                f"{'browser up, fresh tab next' if still_up else 'browser process gone, relaunch next'}"
                f" (tab_fail_streak={tab_fail_streak}/{TAB_FAILS_BEFORE_BROWSER})")
            await asyncio.sleep(wait_s)


def main():
    parser = argparse.ArgumentParser(description="Autonomous Miner Daemon")
    parser.add_argument("--session", required=True, help="Session (e.g. session-2 or 2)")
    parser.add_argument("--project", required=True, help="Lovable project ID")
    parser.add_argument("--browser", default="chromium", choices=["chromium", "firefox"])
    parser.add_argument("--threads", type=int, default=16,
                        help="Worker threads (16 fits 1GB Lovable shells; 64 thrashs)")
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
            log("run_daemon returned unexpectedly — hard-kill + continue in 10s")
            try:
                hard_kill_chrome()
            except Exception:
                pass
            time.sleep(10)
        except KeyboardInterrupt:
            log("KeyboardInterrupt — outer loop continues in 5s")
            time.sleep(5)
            if args.mode != "full":
                break
        except BaseException as e:
            # Catch BaseException so SystemExit from driver death still restarts
            if isinstance(e, KeyboardInterrupt):
                log("KeyboardInterrupt — outer loop continues in 5s")
                time.sleep(5)
                if args.mode != "full":
                    break
                continue
            log(f"Outer error (hard-kill + continue in 10s): "
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
