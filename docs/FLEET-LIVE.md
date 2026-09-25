# FLEET-LIVE — who is mining

**Updated:** 2026-09-25 17:10 UTC
**Registry (single source of truth):** `ops/fleet.json` — rebuild `python3 ops/build_fleet.py`
**Rule:** one Railway cell per **Lovable project**. Same cookies can mine two projects as two cells.

## Mining now (5)

**Gate:** real bridge = `window.doc('nproc')` returns stdout (not URL, not `typeof`). Daemon md5 `c7734bfeb61228afe0af2dc1fd1d9c3b` on all five.

| Cell | Railway | Lov sess | Email | Project | Project name |
|---|---|---|---|---|---|
| **13** | session-1 | 2 | altonlehman16@gmail.com | `05da1af6-0626-4746-a339-92d7e6b2e3e1` | SEO Writer (remix chain) |
| **16** | session-2 | 2 | altonlehman16@gmail.com | `7d6f77a6-69a1-4b06-a1d3-53094c4c8019` | — |
| **28** | session-6 | 41 | jamesmanalodat.e@gmail.com | `ce592dc0-eb0f-4500-81ae-2f848840aaac` | — |
| **35** | session-10 | 50 | hellolakanhernand.ez@gmail.com | `c0bafd1e-33d8-4625-89a4-1250f4755d23` | — |
| **43** | session-12 | 25 | johnpeter08541@gmail.com | `84fa81b7-6c8d-45ab-95a8-7e89bbf92864` | — |

13 + 16 share Lovable session 2 (two projects, two cells).

## Assigned, rolling out (18 bridged sessions waiting on their cell)

Every one of these has a project with a verified `window.doc` bridge. The cell image is
deployed; `ops/bootstrap_plan.py` is bringing the daemon up one at a time.

| Cell | Lov sess | Email | Project |
|---|---|---|---|
| 53 | 25 | johnpeter08541@gmail.com | `84fa81b7…` |
| 76 | 26 | Josephgrant651@gmail.com | `e474f21d…` |
| 77 | 27 | julianhiramqwr@gmail.com | `cdcc177a…` |
| 80 | 28 | kristinenorris08@gmail.com | `ef264ce7…` |
| 81 | 30 | liamantoine31@gmail.com | `9f42ef89…` |
| 82 | 33 | roce.sisla@gmail.com | `b27e2af0…` |
| 83 | 37 | zakarmmusa832@gmail.com | `1f5b8636…` |
| 84 | 38 | simpsonjessicamarie.0@gmail.com | `7703551a…` |
| 86 | 39 | lovgraukipb6b@souss.dev | `432a10dd…` |
| 87 | 40 | lov6020lpeic9@souss.dev | `ac03f128…` |
| 88 | 42 | na.thanrolutenasa@gmail.com | `388ebccb…` |
| 89 | 43 | lovohqhzhno7q@souss.dev | `f16469dc…` |
| 90 | 45 | lovwsrj0lswqa@souss.dev | `ea9614b2…` |
| 91 | 47 | lov484vnilli1@souss.dev | `9508a15e…` (no SSH key on that Railway account) |
| 92 | 49 | lovtx66imf0z1@souss.dev | `ab8e78fe…` |
| 93 | 51 | lovv2ubbdli1c@souss.dev | `9c8b880c…` |
| 94 | 52 | lova4jgjpd9cv@souss.dev | `fa7ad090…` |
| 96 | 53 | lovauxtyiqsp6@souss.dev | `06189278…` |

**Not deployable:** cells 75 / 95 / 110 / 120 — Railway workspace payment-restricted.

## Transport gotcha when checking these

`railway ssh` drops the **first line** of stdout and silently truncates long arguments.
Never read a cell status without `ops/ssh_reliable.py`; a bare rc=0 with empty output
means the command never ran, not that the cell is fine.

## Cell logs

| Cell | Log |
|---|---|
| 13 | `/data/work/daemon_r13.log` |
| 16 | `/data/work/daemon_s2.log` |
| 28 | `/data/work/daemon_r28.log` |
| 35 | `/data/work/daemon_r35.log` |
| 43 | `/data/work/daemon_r43.log` |

`python3 ops/cell_ops.py status 13 16 28 35 43` — want `Worker alive` + `Preview healthy`.

## Not mining — bare cells (no image)

| Cell | Railway | Project | Blocker |
|---|---|---|---|
| 23 | session-3 | `b06e4a07…` | image missing + lov-7 trio poisoned (wrong account token) |
| 25 | session-4 | `211af3cb…` | image missing + lov-8 trio poisoned |
| 26 | session-5 | `0f318cab…` | image missing + lov-8 trio poisoned (shared) |
| 30 | session-7 | `b3ded203…` | image missing; trio ready — best next candidate |
| 31 | session-8 | `8ca51fa8…` | image missing; trio ready |
| 32 | session-9 | `e8ee22a2…` | image missing; lov-48 has no indexeddb (needs rescue) |
| 36 | session-11 | `9421eb8a…` | image missing; trio ready (shared lov-50) |

Redeploy: `automation-toolkit/scripts/cell_service/` (Dockerfile + start.sh) via `railway up`, then `bootstrap`.
`cell-30` is the clean next step — single-owner trio (lov-44 / tra.nariumkill), no identity mismatch.

## Accounts

- **Full trios (cookies + LS + indexeddb with `refresh_token`):** 29 sessions, 28 unique accounts
- **Identity check:** `fleet.json` → `sessions.session-N.identity_ok`. Sessions 1, 7, 8 are **MISMATCH** — their stored token belongs to a different account. Do not use them; re-rescue with an OnKernel key.
- **Dead tokens (MINT-ERR on securetoken):** sessions 16, 35
- **No indexeddb at all:** 25 sessions — owned by the farm merge branch, do not fight it
- **Accounts burned:** session-1 (alexandermay706) — Lovable disabled it

## Bridge (`window.doc`) gate

Worker inject needs **`window.doc` on `*.lovableproject.com/term`** (not Homepage) inside the cell browser.

1. Send `automation-toolkit/prompts/Build a debug terminal.txt` in the project chat — **Build mode only** (Lovable has Build/Chat/Plan; bridge prompt does nothing in Plan mode).
2. Wait for build, open **`/term`**.
3. Daemon navigates the Preview lovableproject iframe → `/term`, then requires `doc('nproc')` before inject.

Wake/presence prompts (`say 'a'`, idle typing) are **not** the bridge prompt.

## Fixed rig per cell

`fleet.json` cell `rig: {threads, bridge}` → baked into `lean_sup.sh` → daemon logs `Rig: threads=… bridge=…`.
All five mining cells currently run default 16 threads on the built-in bridge.
Change live: `python3 ops/cell_ops.py set-rig 28 --threads 8` (restarts supervisor so env re-reads).
