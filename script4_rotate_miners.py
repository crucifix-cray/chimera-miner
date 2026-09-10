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


async def chat_wake(page, pid: str, tag: str) -> bool:
    """Cold previews have no bridge until the dev server wakes. Proven path
    (script3): send a trivial chat prompt, wait, return to preview."""
    try:
        print(f"[{tag}] 💬 waking via chat...", flush=True)
        await asyncio.wait_for(
            page.goto(f"https://lovable.dev/projects/{pid}",
                      timeout=25000, wait_until="domcontentloaded"),
            timeout=40,
        )
        await asyncio.sleep(4)
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
        print(f"[{tag}] ✅ prompt sent, waiting 90s for dev server...", flush=True)
        await asyncio.sleep(90)
        await asyncio.wait_for(
            page.goto(f"https://{pid}.lovableproject.com",
                      timeout=25000, wait_until="domcontentloaded"),
            timeout=40,
        )
        await asyncio.sleep(8)
        return True
    except Exception as e:
        print(f"[{tag}] chat-wake warn: {str(e)[:100]}", flush=True)
        return False


async def tend_tab(page, pid: str, dwell: int, threads: int) -> str:
    """One rotation visit: restore if dead, verify worker, inject if missing,
    human moves for dwell seconds. Returns status string."""
    ts = datetime.now().strftime("%H:%M:%S")
    tag = pid[:8]
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await asyncio.sleep(2)

    if not await is_tab_alive(page):
        print(f"[{ts}] [{tag}] 💥 tab dead — restoring...")
        if not await restore_tab(page, f"https://{pid}.lovableproject.com"):
            return "dead"

    # find preview frame (preview IS the page here, but keep frame logic)
    try:
        frames = page.frames
        frame = next(
            (f for f in frames if "lovableproject" in f.url.lower()),
            page.main_frame,
        )
    except Exception:
        return "dead"

    running = await verify_worker(frame)
    if not running:
        # cold preview? wake via chat, then re-check bridge before inject
        nobridge = False
        try:
            has_bridge = await frame.evaluate(
                "(() => !!(window.doc && typeof window.doc === 'function'))()")
        except Exception:
            has_bridge = False
        if not has_bridge:
            nobridge = True
            if await chat_wake(page, pid, tag):
                try:
                    frames = page.frames
                    frame = next(
                        (f for f in frames if "lovableproject" in f.url.lower()),
                        page.main_frame,
                    )
                    running = await verify_worker(frame)
                    if running:
                        print(f"[{tag}] ✅ worker already up after wake", flush=True)
                except Exception:
                    pass
        if not running:
            print(f"[{ts}] [{tag}] ⚙️ worker missing{' (no bridge, wake failed)' if nobridge else ''} — injecting...",
                  flush=True)
            ok = await inject_miner(page, threads=threads)
            print(f"[{ts}] [{tag}] {'✅ worker up' if ok else '❌ inject failed'}")
            if not ok:
                return "no-worker"

    print(f"[{ts}] [{tag}] 👀 dwelling {dwell}s...")
    await human_moves(page, dwell)
    return "ok"


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

    async with InvisiblePlaywright(
        headless=True,
        proxy=proxy,
        humanize=False,
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

        print("✅ starting single-tab rotation loop", flush=True)
        round_n = 0
        while True:
            round_n += 1
            print(f"\n{'='*50}\n🔁 ROUND {round_n} @ {datetime.now().strftime('%H:%M:%S')}\n{'='*50}", flush=True)
            for pid in pids:
                tag = pid[:8]
                pg = await open_tab(f"https://{pid}.lovableproject.com", tag)
                if pg is None:
                    print(f"   [{tag}] round done: open-failed", flush=True)
                    continue
                try:
                    status = await tend_tab(pg, pid, args.dwell, args.threads)
                    print(f"   [{tag}] round done: {status}", flush=True)
                except Exception as e:
                    print(f"   [{tag}] round error: {str(e)[:120]}", flush=True)
                finally:
                    try:
                        await pg.close()
                    except Exception:
                        pass


if __name__ == "__main__":
    asyncio.run(main())
