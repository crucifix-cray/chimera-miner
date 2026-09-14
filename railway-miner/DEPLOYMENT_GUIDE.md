# Railway Deployment Guide

## Prerequisites

1. **Railway Account**: https://railway.app
2. **Railway CLI**: `npm i -g @railway/cli` or `brew install railway`
3. **Authenticated**: `railway login`
4. **Project Linked**: `railway link` in this directory

## Quick Start (When Working)

```bash
# Deploy
railway up

# Check status
railway status

# View logs (web dashboard works better)
railway logs
```

## Current Blocker: Railpack Override

Railway keeps using Railpack (Python auto-detector) which doesn't install system dependencies.

### What Railpack Does
1. Detects `requirements.txt`
2. Ignores `Dockerfile`, `nixpacks.toml`, `railway.toml`
3. Runs: `pip install -r requirements.txt`
4. Starts with `sleep infinity` (or Procfile command)
5. ❌ **Does NOT install Xvfb, Firefox, or system packages**

### What We Need
1. Install system packages: `xvfb firefox-esr git procps`
2. Install Python deps: `playwright pyotp`
3. Install Playwright browsers: `playwright install firefox`
4. Start command: `python3 run_miner.py`

## Solution Attempts

### Attempt 1: Add Dockerfile (FAILED)
Railway has `Dockerfile` but ignores it due to Python detection.

**Fix Options**:
1. **Remove requirements.txt** before deploy, restore after
2. **Use Railway Dashboard** to manually select Docker builder
3. **Add RAILWAY_DOCKERFILE_PATH** environment variable

### Attempt 2: Use nixpacks.toml (FAILED)
Created `nixpacks.toml` with system packages, Railway ignored it.

### Attempt 3: Use railway.toml (FAILED)
```toml
[build]
builder = "NIXPACKS"
```
Railway still used Railpack.

## Working Solution (TO TEST)

### Method 1: Force Docker via Dashboard

1. Open Railway dashboard: https://railway.com/project/2e7ef06d-660e-4da2-87e3-1cc37693889b
2. Go to service `ubuntu`
3. Settings → Builder → Select **Docker**
4. Redeploy

### Method 2: Remove requirements.txt Trick

```bash
# Backup requirements.txt
mv requirements.txt requirements.txt.bak

# Deploy (Railway won't detect Python)
railway up

# Restore
mv requirements.txt.bak requirements.txt

# Commit restored version
git add requirements.txt
git commit -m "restore requirements.txt"
```

### Method 3: Use .nixpacks/plan.json

Create `.nixpacks/plan.json`:
```json
{
  "phases": {
    "setup": {
      "nixPkgs": ["xvfb", "firefox-esr"],
      "aptPkgs": ["git", "procps"]
    },
    "install": {
      "cmds": [
        "pip install -r requirements.txt",
        "playwright install firefox",
        "playwright install-deps firefox || true"
      ]
    }
  },
  "start": {
    "cmd": "python3 run_miner.py"
  }
}
```

## Resource Requirements

### Minimum
- **RAM**: 2GB (1GB too tight for Firefox + Playwright)
- **CPU**: 2 vCPU
- **Disk**: 1GB

### Recommended
- **RAM**: 4GB (comfortable for browser + miner)
- **CPU**: 4 vCPU
- **Disk**: 2GB

### Upgrade Railway Plan
If on free tier (512MB RAM):
```bash
# Check current limits
railway usage

# Upgrade in dashboard:
# https://railway.com/account/billing
```

## Environment Variables

Set in Railway dashboard or via CLI:

```bash
railway variables set DISPLAY=:99
railway variables set CHIMERA_NO_PROXY=1
railway variables set CHIMERA_HEADED=1
railway variables set CHIMERA_NO_MEGA=1
railway variables set PYTHONUNBUFFERED=1
```

Or add to `railway.toml`:
```toml
[deploy]
startCommand = "python3 run_miner.py"

[[deploy.environmentVariables]]
name = "DISPLAY"
value = ":99"

[[deploy.environmentVariables]]
name = "CHIMERA_NO_PROXY"
value = "1"

[[deploy.environmentVariables]]
name = "CHIMERA_HEADED"
value = "1"

[[deploy.environmentVariables]]
name = "CHIMERA_NO_MEGA"
value = "1"

[[deploy.environmentVariables]]
name = "PYTHONUNBUFFERED"
value = "1"
```

## Monitoring

### Check Status
```bash
railway status
```

### View Logs (CLI - Limited)
```bash
railway logs --lines 100
railway logs --build    # Build logs
```

### View Logs (Web Dashboard - Better)
1. Open: https://railway.com/project/2e7ef06d-660e-4da2-87e3-1cc37693889b/service/f507bc6f-a72c-40be-b7ed-6fbb08e89c2a
2. Click "Deployments"
3. Select latest deployment
4. View "Build Logs" and "Deploy Logs"

### Check if Running
Look for these log lines:
```
🚀 RAILWAY MINER DEPLOYMENT (Memory Optimized)
✅ Environment configured
✅ Xvfb started on :99
✅ Browser launched
📝 Going to project...
💬 Sending prompt...
✅ Prompt sent
🌐 Opening preview...
⏳ Waiting for console ready...
✅ Console ready!
💉 Injecting miner...
✅ Miner injected!
🏥 Starting health loop...
```

### Health Check Endpoint (Future)
Add health endpoint to run_miner.py:
```python
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

def start_health_server():
    server = HTTPServer(('0.0.0.0', 8080), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

# In main():
start_health_server()
```

## Debugging

### Build Fails
**Check build logs:**
```bash
railway logs --build --lines 200
```

**Common issues:**
- Missing Dockerfile (Railpack used instead)
- Python version mismatch
- Dependency conflicts (pyee version clash)

### Runtime Crashes
**Check deploy logs:**
```bash
railway logs --deployment --lines 200
```

**Common issues:**
- Out of memory (OOM) → Upgrade RAM
- Browser crash → Check Firefox args, reduce memory usage
- Timeout → Increase timeouts in script, check network

### Can't See Logs
**Use web dashboard:**
https://railway.com/project/2e7ef06d-660e-4da2-87e3-1cc37693889b/service/f507bc6f-a72c-40be-b7ed-6fbb08e89c2a

**Or try:**
```bash
railway logs --json | jq .
```

### Container Exits Immediately
**Check start command:**
- Should be: `python3 run_miner.py`
- NOT: `sleep infinity`

**Verify in railway.toml or Procfile:**
```
# Procfile
web: python3 run_miner.py
```

## Rollback

### To Previous Deployment
```bash
# List deployments
railway deployment list

# Rollback to specific ID
railway deployment rollback <deployment-id>
```

### Redeploy Current
```bash
railway redeploy
```

## Local Testing

Before deploying to Railway, test locally:

```bash
# Install deps
pip install -r requirements.txt
playwright install firefox

# Set env vars
export DISPLAY=:0
export CHIMERA_NO_PROXY=1
export CHIMERA_HEADED=1
export CHIMERA_NO_MEGA=1
export CHIMERA_SESSIONS_DIR=$(pwd)/sessions
export CHIMERA_TOOLKIT_CORE=$(pwd)/core
export PYTHONUNBUFFERED=1

# Run (not in background for testing)
python3 run_miner.py
```

**Should see:**
- Browser window opens (if DISPLAY=:0 and headed)
- Logs appear in terminal
- Chat page loads
- Preview page opens
- Console ready detected
- Miner injected
- Health loop starts

## Alternative: Docker Local Test

```bash
# Build
docker build -t railway-miner .

# Run
docker run -it --rm \
  -e DISPLAY=:99 \
  -e CHIMERA_NO_PROXY=1 \
  -e CHIMERA_HEADED=1 \
  -e CHIMERA_NO_MEGA=1 \
  railway-miner
```

**Should work if Railway uses Docker properly.**

## Next Deploy Checklist

- [ ] Remove requirements.txt OR force Docker builder
- [ ] Verify RAM >= 2GB in Railway settings
- [ ] Set all environment variables
- [ ] Deploy: `railway up`
- [ ] Check build logs for Dockerfile execution
- [ ] Check deploy logs for script startup
- [ ] Verify browser launch (look for Firefox process)
- [ ] Confirm miner injection (check log for "✅ Miner injected!")
- [ ] Monitor for 10+ minutes (ensure no crashes)
- [ ] Check health loop is running (logs every 3min)

## Success Criteria

Deployment is successful when:
1. ✅ Build uses Dockerfile (not Railpack)
2. ✅ Container starts without crashing
3. ✅ Xvfb starts on :99
4. ✅ Firefox launches successfully
5. ✅ Logs into Lovable project
6. ✅ Opens preview page
7. ✅ Detects console ready (window.doc)
8. ✅ Injects miner command
9. ✅ Health loop runs continuously
10. ✅ Worker stays alive (no restarts)

## Failure Scenarios

### Scenario 1: Railpack Used
**Symptom**: Build logs show "Railpack 0.39.0", no Dockerfile steps  
**Cause**: Railway detected Python, ignored Dockerfile  
**Fix**: Remove requirements.txt or force Docker builder

### Scenario 2: OOM Kill
**Symptom**: Container exits with code 137  
**Cause**: Out of memory  
**Fix**: Upgrade to 2GB+ RAM plan

### Scenario 3: Browser Crash
**Symptom**: "TargetClosedError", "Browser closed"  
**Cause**: Firefox crash due to resource constraints  
**Fix**: Add more RAM, reduce browser flags, use --single-process

### Scenario 4: Injection Fails
**Symptom**: "❌ Injection failed"  
**Cause**: Console not ready (no window.doc function)  
**Fix**: Increase wait time, verify preview URL correct, check sandbox status

### Scenario 5: Health Loop Kills Worker
**Symptom**: Miner stops after health check  
**Cause**: Page reload kills WebContainer  
**Fix**: Remove preview_page.reload() from health check, only check with evaluate()

## Support

If deployment still fails after following this guide:

1. **Check Railway Status**: https://status.railway.app
2. **Railway Discord**: https://discord.gg/railway
3. **Review Build Logs**: Especially for Railpack vs Docker detection
4. **Try Alternative Provider**: Render, Fly.io, DigitalOcean

## Related Files

- `README.md` - Main documentation
- `run_miner.py` - Entry point script
- `Dockerfile` - Docker build config (currently ignored)
- `requirements.txt` - Python dependencies
- `railway.toml` - Railway configuration
- `Procfile` - Process configuration
