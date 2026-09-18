#!/usr/bin/env python3
"""Local headed Camoufox: session-3 → project chat + *.lovableproject.com."""
import asyncio
import json
from pathlib import Path

from camoufox.async_api import AsyncCamoufox

SESS = Path("/home/alae/Documents/repos/automation-toolkit/scripts/sessions/session-3")
PROJECT = "7d6f77a6-69a1-4b06-a1d3-53094c4c8019"
CHAT = f"https://lovable.dev/projects/{PROJECT}"
PREVIEW = f"https://{PROJECT}.lovableproject.com"


async def main():
    cookies = json.loads((SESS / "cookies.json").read_text())
    print(f"session-3 cookies={len(cookies)}", flush=True)
    print(f"PROJECT={PROJECT}", flush=True)
    print(f"CHAT={CHAT}", flush=True)
    print(f"PREVIEW={PREVIEW}", flush=True)

    async with AsyncCamoufox(headless=False, humanize=False) as browser:
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
        await ctx.add_cookies(cookies)

        print("→ chat…", flush=True)
        await page.goto(CHAT, timeout=120000, wait_until="domcontentloaded")
        await asyncio.sleep(5)
        print(f"chat url={page.url} title={await page.title()}", flush=True)

        print("→ lovableproject.com…", flush=True)
        await page.goto(PREVIEW, timeout=120000, wait_until="domcontentloaded")
        await asyncio.sleep(8)
        for i in range(40):
            u = page.url or ""
            if "auth-bridge" not in u and "auth-token" not in u:
                break
            print(f"  bridging… {u[:100]}", flush=True)
            await asyncio.sleep(2)
        print(f"preview url={page.url}", flush=True)

        try:
            r = await asyncio.wait_for(
                page.evaluate(
                    """async () => {
                      const res = await fetch('/__shell', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({cmd: 'pwd'})
                      });
                      return {status: res.status, body: (await res.text()).slice(0, 200)};
                    }"""
                ),
                timeout=45,
            )
            print(f"SHELL {r}", flush=True)
        except Exception as e:
            print(f"SHELL fail: {type(e).__name__}: {e}", flush=True)

        print("Browser open 10 minutes — look at the Camoufox window.", flush=True)
        await asyncio.sleep(600)


if __name__ == "__main__":
    asyncio.run(main())
