# Game Credentials - Railway Acc Playing With

**Game:** `fix/script2-3mode` 3-mode heavy

---

## Railway Acc (VPN Sandbox - isolated)

- **Email:** `g.runsts.wain36+jywh3i0b@gmail.com`
- **Token:** `[REDACTED-RAILWAY-TOKEN - see railway-token.txt]` (from `railway-token.txt` in `railway-vpn-sandbox/`)
- **Session:** `/tmp/my-railway-session/.railway/config.json` (separate HOME, not `~/.railway`)
- **Sandbox:** `6d37bdd4-35e6-46e1-a014-0776000ddc13` project `ubuntu-sbx` `4df298dd-1ab8-4ce5-8aa0-20bdf0ffa567` env `production` region `us-west2` checkpoint `vpn`
- **Egress IP:** `152.55.177.190` (US) via `tun0` `10.8.0.1/10.8.0.2` `proto tcp-server 1194` `cipher AES-256-CBC` - split routing `curl --interface tun0 ifconfig.me` vs direct
- **Client:** `railway-vpn-sandbox/client.ovpn` + `static.key` (shared static-key, `allow-deprecated-insecure-static-crypto` on client)
- **Usage:** `HOME=/tmp/my-railway-session railway sandbox create --checkpoint vpn` then `railway sandbox exec -- service openvpn start` + `railway sandbox forward 1194` → `localhost:1194` → `openvpn --config client.ovpn`

> WARNING: token grants full GraphQL `backboard.railway.com` control - repo private, rotate if leaks.

---

## Lovable Sessions For Game

- **Primary:** `session-19 Josephgrant651@gmail.com` `password Josephgrant651@gmail.com` `created_at 2026-08-16` `cookies 52` `active`
- **Secondary:** `session-21 mariepeterson749@gmail.com` `password mariepeterson749@gmail.com` `active` `0 projects`
- **Path:** `/home/alan/Documents/automation-toolkit/scripts/sessions/session-{19,21}/` (`config.json` + `cookies.json`)
- **DB:** `mega:chimera/database.json` via `rclone` (`mega` remote `emilypeterson30@mail.findmeghana.org`) - `env -u HTTP_PROXY` required

---

## GitHub For Game

- **Host:** `crucifix-cray` (MAIN) - `[REDACTED-GH-TOKEN - see local]` (provided)
- **Repos:** `crucifix-cray/automation-toolkit` (workflows) + `crucifix-cray/chimera-miner` (this game)
- **Runners:** `amineborkadi` / `helvetica-tilde` / `mixtape-swagg` (checkout only, never host)
- **Dead:** `taxidermy-organic` `accbroly1` `helvetica-brunch` `alae` - suspended

---

## Warp For Game (isolated)

- **Mode:** `warp-cli mode proxy` `WarProxy on port 40000` (not `wg-quick` system-wide)
- **Proxy:** `socks5://127.0.0.1:40000` `bypass api.tempmailhub.org,api.lovable.dev,127.0.0.1,localhost` (fixes `ERR_SOCKS_CONNECTION_FAILED api.lovable.dev`)
- **Verify:** `browser warp=on colo LIS ip 2a09:bac1:46a0:28::6b:84` vs `direct warp=off colo WAW`
- **Status:** `warp-cli status` `Connected` `warp-svc` pid `594`

---

## Mega For Game

- **Encrypted:** `U2FsdGVkX1+7o1RU...` password `0770` → `rclone.conf` `[mega]` (see `automation-toolkit/docs/CREDENTIALS.md`)
- **Remotes:** `mega:chimera/database.json` (sessions+projects) + `mega:lovable_sessions/invites.json` (2 invites `6c09b9fd` `99b571e6` usage 0/1)

---

## How To Use

```bash
export HOME=/tmp/my-railway-session
railway whoami # should show g.runsts...
# warp already proxy, no need to up wg-quick
curl --socks5 127.0.0.1:40000 https://cloudflare.com/cdn-cgi/trace | grep warp # on
python3 -u script2_remix_link.py --session 19 --mode template --count 1 # uses warp proxy + bypass
```
