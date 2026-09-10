#!/usr/bin/env python3
"""Visual probe: settings deep-link -> wheel scroll -> Remix pill -> dialog.
Saves /tmp/probe_A/B/C.png for human inspection."""
import asyncio
import json
import os
import sys

sys.path.insert(0, "/home/alan/Documents/repos/automation-toolkit/finals/core")
from invisible_playwright.async_api import InvisiblePlaywright

SESS = "/home/alan/Documents/repos/automation-toolkit/scripts/sessions/session-1"
PID = "9941886d-d66f-4be6-8c77-5517809a36bb"


async def main():
    cks = json.load(open(os.path.join(SESS, "cookies.json")))
    async with InvisiblePlaywright(headless=True, proxy=None, humanize=False, locale="en-US") as b:
        ctx = b.contexts[0] if b.contexts else await b.new_context(viewport={"width": 1440, "height": 900})
        await ctx.add_cookies(cks)
        p = await ctx.new_page()
        await p.goto(
            f"https://lovable.dev/projects/{PID}?view=more&subview=settings-general",
            timeout=60000,
            wait_until="domcontentloaded",
        )
        await asyncio.sleep(8)
        print("url:", p.url)
        try:
            await p.get_by_role("button", name="General").first.wait_for(state="visible", timeout=20000)
            print("General: VISIBLE")
        except Exception:
            print("General: MISSING")
        await p.screenshot(path="/tmp/probe_A.png")
        print("saved A")
        panel = p.locator("#preview-panel").first
        try:
            await panel.wait_for(state="attached", timeout=15000)
            print("#preview-panel: ATTACHED")
        except Exception:
            print("#preview-panel: MISSING")
        for i in range(4):
            try:
                box = await panel.bounding_box()
                if box:
                    await p.mouse.move(box["x"] + box["width"] * 0.75, box["y"] + box["height"] - 120)
                    await p.mouse.wheel(0, 900)
            except Exception as e:
                print("wheel err:", str(e)[:80])
            await asyncio.sleep(1.5)
        await p.screenshot(path="/tmp/probe_B.png")
        print("saved B")
        pill = panel.get_by_role("button", name="Remix", exact=True).first
        try:
            await pill.wait_for(state="visible", timeout=8000)
            print("pill: VISIBLE, enabled:", await pill.is_enabled())
        except Exception:
            print("pill: NOT VISIBLE")
            try:
                print("pill count:", await pill.count())
            except Exception:
                pass
        try:
            await pill.click(timeout=10000)
            print("pill: CLICKED")
        except Exception as e:
            print("pill click err:", str(e)[:120])
        await asyncio.sleep(6)
        await p.screenshot(path="/tmp/probe_C.png")
        print("saved C")
        try:
            body = (await p.content()).lower()
            print("has remix dialog:", "remix project" in body and "acknowledge" in body or "target workspace" in body)
            print("new url:", p.url)
        except Exception as e:
            print("content err:", str(e)[:100])
        await ctx.close()


asyncio.run(main())
