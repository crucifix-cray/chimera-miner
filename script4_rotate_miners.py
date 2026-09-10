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
        print(f"[{ts}] [{tag}] ⚙️ worker missing — injecting...")
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
        context = browser.contexts[0] if browser.contexts else await browser.new_context(viewport={"width": 1280, "height": 720})
        try:
            await context.add_cookies(cookies)
        except Exception as e:
            print(f"⚠️ cookie load warn: {str(e)[:120]}")

        # login check on first tab (domcontentloaded: "load" hangs on
        # stray trackers, esp. on fresh networks)
        probe = await context.new_page()
        try:
            await probe.goto("https://lovable.dev/", timeout=30000,
                             wait_until="domcontentloaded")
        except Exception as e:
            print(f"⚠️ probe goto warn: {str(e)[:100]}")
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

        # open one tab per project (preview URL directly)
        tabs = []
        for pid in pids:
            pg = await context.new_page()
            try:
                await pg.goto(f"https://{pid}.lovableproject.com", timeout=30000,
                              wait_until="domcontentloaded")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"⚠️ [{pid[:8]}] open warn: {str(e)[:100]}")
            tabs.append((pid, pg))
        print(f"✅ {len(tabs)} tabs open — starting rotation loop")

        round_n = 0
        while True:
            round_n += 1
            print(f"\n{'='*50}\n🔁 ROUND {round_n} @ {datetime.now().strftime('%H:%M:%S')}\n{'='*50}")
            for pid, pg in tabs:
                try:
                    status = await tend_tab(pg, pid, args.dwell, args.threads)
                    print(f"   [{pid[:8]}] round done: {status}")
                except Exception as e:
                    print(f"   [{pid[:8]}] round error: {str(e)[:120]}")


if __name__ == "__main__":
    asyncio.run(main())
