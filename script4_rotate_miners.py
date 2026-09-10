#!/usr/bin/env python3
"""
Script 4: rotate 10 project previews in ONE headless browser.

- 1 browser, 1 tab per project (preview URL directly, no chat needed)
- loop forever: focus tab -> human moves (2-3 min dwell) -> verify worker
  -> re-inject if missing -> restore tab if crashed -> next tab
- miners run server-side in Lovable sandboxes; tabs are just babysitters
  that keep previews from idling and re-attach the bridge on crash.

Usage:
  MINER_CMD='...' python3 -u script4_rotate_miners.py \
    --session 1 --db local --threads 64 --dwell 150 \
    --projects 9941886d-...,55e09bdc-...,...
"""
import argparse
import asyncio
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from invisible_playwright.async_api import InvisiblePlaywright

from miner_injector import (
    inject_miner,
    is_tab_alive,
    restore_tab,
    verify_worker,
)
from script3_launch_miner import (
    load_session_cookies,
    check_session_valid,
    relogin_session,
    resolve_proxy,
    wait_for_console_message,
)

SESSIONS_DIR = Path(
    os.environ.get(
        "CHIMERA_SESSIONS_DIR",
        "/home/alan/Documents/repos/automation-toolkit/scripts/sessions",
    )
)

LOWMEM_PREFS = {
    "browser.cache.memory.capacity": 65536,
    "browser.sessionhistory.max_entries": 5,
    "dom.ipc.processCount": 4,
}


async def human_moves(page, seconds: int):
    """Small human-like activity for `seconds`: mouse moves + tiny scrolls."""
    end = asyncio.get_event_loop().time() + seconds
    try:
        w = await page.evaluate("window.innerWidth || 1280")
        h = await page.evaluate("window.innerHeight || 720")
    except Exception:
        w, h = 1280, 720
    while asyncio.get_event_loop().time() < end:
        try:
            await page.mouse.move(
                random.randint(100, max(101, int(w) - 100)),
                random.randint(100, max(101, int(h) - 100)),
                steps=random.randint(3, 8),
            )
            await asyncio.sleep(random.uniform(4, 9))
            if random.random() < 0.4:
                await page.mouse.wheel(0, random.choice([-240, 240, 400]))
                await asyncio.sleep(random.uniform(2, 5))
        except Exception:
            return


CHAT_SELECTORS = ['div[contenteditable="true"][role="textbox"]',
                  '[contenteditable="true"]',
                  'textarea[placeholder*="chat"]', 'textarea']


async def wait_chat_ready(page, url: str, tag: str, timeout: int = 180) -> bool:
    """Refresh until the chat app actually mounts (input visible).
    Chat pages often sit white while the SPA stalls — same disease as
    preview 502s, same cure: refresh till alive."""
    end = asyncio.get_event_loop().time() + timeout
    tries = 0
    while asyncio.get_event_loop().time() < end:
        tries += 1
        try:
            if not await is_tab_alive(page):
                print(f"[{tag}] chat gate: tab dead", flush=True)
                return False
            for sel in CHAT_SELECTORS:
                try:
                    el = await page.wait_for_selector(sel, timeout=8000,
                                                      state="visible")
                    if el and await el.is_visible():
                        print(f"[{tag}] ✅ chat mounted ({tries} tries)", flush=True)
                        return True
                except Exception:
                    continue
            print(f"[{tag}] ⏳ chat white, refreshing... ({tries})", flush=True)
            try:
                await page.reload(timeout=25000, wait_until="domcontentloaded")
            except Exception:
                pass
            await asyncio.sleep(8)
        except Exception as e:
            print(f"[{tag}] chat gate warn: {str(e)[:100]}", flush=True)
            await asyncio.sleep(8)
    print(f"[{tag}] ❌ chat never mounted after {timeout}s", flush=True)
    return False


async def send_chat_prompt(page, tag: str) -> bool:
    """Find chat input and fire a trivial trigger prompt. No waiting."""
    try:
        chat_input = None
        for sel in ['div[contenteditable="true"][role="textbox"]',
                    '[contenteditable="true"]',
                    'textarea[placeholder*="chat"]', 'textarea']:
            try:
                el = await page.wait_for_selector(sel, timeout=5000, state="visible")
                if el and await el.is_visible() and await el.is_enabled():
                    chat_input = el
                    break
            except Exception:
                continue
        if not chat_input:
            print(f"[{tag}] ❌ no chat input", flush=True)
            return False
        prompt = random.choice(["say 'a'", "1+1?", "say 'x'", "2+2?"])
        await chat_input.fill(prompt)
        await asyncio.sleep(0.3)
        await page.keyboard.press("Enter")
        print(f"[{tag}] ✅ prompt sent: '{prompt}'", flush=True)
        return True
    except Exception as e:
        print(f"[{tag}] prompt warn: {str(e)[:100]}", flush=True)
        return False


async def wait_bridge(page, tag: str, timeout: int = 120) -> bool:
    """Poll until window.doc bridge exists (dev server booted the app)."""
    end = asyncio.get_event_loop().time() + timeout
    tried = 0
    while asyncio.get_event_loop().time() < end:
        tried += 1
        try:
            if not await is_tab_alive(page):
                print(f"[{tag}] bridge wait: tab dead", flush=True)
                return False
            has = await page.evaluate(
                "(() => !!(window.doc && typeof window.doc === 'function'))()")
            if has:
                print(f"[{tag}] ✅ bridge up ({tried} checks)", flush=True)
                return True
        except Exception:
            pass
        await asyncio.sleep(10)
    print(f"[{tag}] ❌ no bridge after {timeout}s", flush=True)
    return False


async def preview_frame(page):
    try:
        frames = page.frames
        return next(
            (f for f in frames if "lovableproject" in f.url.lower()),
            page.main_frame,
        )
    except Exception:
        return None


async def tend_project(context, open_tab, pid: str, dwell: int, threads: int) -> str:
    """The dance per project visit:
    chat tab (prompt) -> preview tab (bridge/worker/dwell).
    Preview burns -> back to chat, re-prompt, preview again.
    Both tabs closed at the end; miners persist server-side."""
    tag = pid[:8]
    chat_url = f"https://lovable.dev/projects/{pid}"
    chat = await open_tab(chat_url, tag + "-chat")
    if chat is None:
        return "chat-open-failed"
    if not await wait_chat_ready(chat, chat_url, tag, timeout=180):
        try:
            await chat.close()
        except Exception:
            pass
        return "chat-never-ready"
    prompted = await send_chat_prompt(chat, tag)

    async def tend_preview(attempt: str) -> str:
        prev = await open_tab(f"https://{pid}.lovableproject.com", tag)
        if prev is None:
            return "preview-open-failed"
        try:
            try:
                await prev.bring_to_front()
            except Exception:
                pass
            # 502/proxy-error? refresh until the JS console shows ready
            # (same "lovable is ready" gate script3 uses).
            print(f"[{tag}] ⏳ waiting console ready (refresh on 502)...", flush=True)
            try:
                ready = await wait_for_console_message(prev, timeout_seconds=150)
            except Exception as e:
                print(f"[{tag}] console-wait warn: {str(e)[:100]}", flush=True)
                ready = False
            if not ready:
                # tab may be a corpse (reload can't resurrect a destroyed
                # target) -> fresh tab, one retry on the live page.
                try:
                    dead = not await is_tab_alive(prev)
                except Exception:
                    dead = True
                if dead:
                    print(f"[{tag}] 💥 corpse tab — opening fresh...", flush=True)
                    try:
                        await prev.close()
                    except Exception:
                        pass
                    prev = await open_tab(f"https://{pid}.lovableproject.com",
                                          tag + "-fresh")
                    if prev is None:
                        return "preview-open-failed"
                    try:
                        ready = await wait_for_console_message(prev, timeout_seconds=150)
                    except Exception as e:
                        print(f"[{tag}] fresh console-wait warn: {str(e)[:100]}",
                              flush=True)
                        ready = False
                if not ready:
                    return "console-never-ready"
            if not await wait_bridge(prev, tag, timeout=120):
                return "no-bridge"
            frame = await preview_frame(prev)
            if frame is None:
                return "dead"
            if await verify_worker(frame):
                print(f"[{tag}] ✅ worker already running ({attempt})", flush=True)
            else:
                print(f"[{tag}] ⚙️ worker missing — injecting ({attempt})...", flush=True)
                ok = await inject_miner(prev, threads=threads)
                print(f"[{tag}] {'✅ worker up' if ok else '❌ inject failed'}", flush=True)
                if not ok:
                    return "no-worker"
            print(f"[{tag}] 👀 dwelling {dwell}s...", flush=True)
            await human_moves(prev, dwell)
            if not await is_tab_alive(prev):
                return "burned"
            return "ok"
        finally:
            try:
                await prev.close()
            except Exception:
                pass

    status = await tend_preview("1st")
    if status in ("burned", "no-bridge", "no-worker", "dead",
                   "console-never-ready"):
        # rescue: back to chat, re-prompt, preview again
        print(f"[{tag}] 🔄 rescue: re-prompt + retry preview...", flush=True)
        try:
            await chat.bring_to_front()
            await asyncio.sleep(1)
            await send_chat_prompt(chat, tag)
            await asyncio.sleep(45)
        except Exception as e:
            print(f"[{tag}] rescue warn: {str(e)[:100]}", flush=True)
        status = await tend_preview("rescue") + "-after-rescue"
    try:
        await chat.close()
    except Exception:
        pass
    return status


async def main():
    ap = argparse.ArgumentParser(description="Script 4: 10-tab rotation miner")
    ap.add_argument("--session", required=True)
    ap.add_argument("--projects", required=True,
                    help="Comma-separated project UUIDs (10)")
    ap.add_argument("--threads", type=int, default=64)
    ap.add_argument("--dwell", type=int, default=150,
                    help="Seconds per tab per visit (default 150)")
    ap.add_argument("--db", choices=["local", "mega", "github"], default="local")
    args = ap.parse_args()

    pids = [p.strip() for p in args.projects.split(",") if p.strip()]
    print(f"🔄 SCRIPT 4: {len(pids)} projects, dwell {args.dwell}s, threads {args.threads}")

    # session + cookies
    sid = args.session.strip()
    if sid.startswith("session-"):
        sid = sid[len("session-"):]
    global SESSIONS_DIR
    sys.path.insert(0, str(Path(__file__).parent))
    import script3_launch_miner as s3
    s3.SESSIONS_DIR = SESSIONS_DIR
    config, cookies = await load_session_cookies(sid)
    print(f"✅ Session: {config.get('email')}")

    proxy = resolve_proxy()
    print(f"🌐 proxy: {'yes' if proxy else 'direct'}")

    _headed = os.environ.get("HEADLESS", "0") != "1"
    async with InvisiblePlaywright(
        headless=not _headed,
        proxy=proxy,
        humanize=_headed,
        extra_prefs=LOWMEM_PREFS,
    ) as browser:
        print("DBG: browser entered", flush=True)
        context = browser.contexts[0] if browser.contexts else await browser.new_context(viewport={"width": 1280, "height": 720})
        print("DBG: context ok", flush=True)
        try:
            await context.add_cookies(cookies)
        except Exception as e:
            print(f"⚠️ cookie load warn: {str(e)[:120]}")
        print("DBG: cookies done", flush=True)

        # login check on first tab (domcontentloaded: "load" hangs on
        # stray trackers, esp. on fresh networks)
        probe = await context.new_page()
        print("DBG: probe page ok", flush=True)
        print("DBG: starting probe goto", flush=True)
        try:
            await asyncio.wait_for(
                probe.goto("https://lovable.dev/", timeout=25000,
                           wait_until="domcontentloaded"),
                timeout=40,
            )
            print("DBG: probe goto done", flush=True)
        except Exception as e:
            print(f"⚠️ probe goto warn: {str(e)[:100]}", flush=True)
        await asyncio.sleep(4)
        try:
            valid = await check_session_valid(probe)
        except Exception:
            valid = False
        if not valid:
            print("🔑 session invalid — relogin...")
            await relogin_session(browser, config, f"session-{sid}")
            await probe.goto("https://lovable.dev/", timeout=45000)
            await asyncio.sleep(4)
        await probe.close()

        # Single-tab rotation: miners live server-side, so tabs are
        # disposable. Open -> tend -> close keeps RAM ~1 tab and dodges
        # wedged-tab/new_page hangs entirely.
        async def open_tab(url: str, tag: str):
            print(f"[{tag}] opening tab...", flush=True)
            try:
                pg = await asyncio.wait_for(context.new_page(), timeout=30)
            except Exception as e:
                print(f"⚠️ [{tag}] new_page warn: {str(e)[:100]}", flush=True)
                return None
            try:
                await asyncio.wait_for(
                    pg.goto(url, timeout=25000, wait_until="domcontentloaded"),
                    timeout=40,
                )
                print(f"[{tag}] loaded: {pg.url[:80]}", flush=True)
                await asyncio.sleep(5)
                return pg
            except Exception as e:
                print(f"⚠️ [{tag}] open warn: {str(e)[:100]}", flush=True)
                try:
                    await pg.close()
                except Exception:
                    pass
                return None

        print("✅ starting chat→preview rotation loop", flush=True)
        round_n = 0
        while True:
            round_n += 1
            print(f"\n{'='*50}\n🔁 ROUND {round_n} @ {datetime.now().strftime('%H:%M:%S')}\n{'='*50}", flush=True)
            for pid in pids:
                tag = pid[:8]
                try:
                    status = await tend_project(context, open_tab, pid,
                                                args.dwell, args.threads)
                    print(f"   [{tag}] round done: {status}", flush=True)
                except Exception as e:
                    print(f"   [{tag}] round error: {str(e)[:120]}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
