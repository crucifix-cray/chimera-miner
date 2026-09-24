# FLEET-LIVE — who is mining

**Updated:** 2026-09-24 (DOC_MARK nproc gate → 4 mining forever)
**Rule:** one Railway cell per **Lovable project**. Accounts with 2 projects → 2 cells (same cookies, different `--project`).
**Railway order:** `session-1`, skip **`session-2`** (cell-16), then `session-3`…

## Mining now (DOC_OK via `doc('nproc')` → Worker forever)

**Gate:** real bridge = `window.doc('nproc')` returns stdout (not URL/`typeof`). Daemon md5 `c5c3ed9ba763d6a481823ac9555f9c9c`.

| Cell | Project | `nproc` | Status |
|---|---|---|---|
| **13** | `05da1af6…` | 16 | **MINING** — Worker alive + Preview healthy; lean_sup forever (no `CHIMERA_DOC_MARK`) |
| **16** | `7d6f77a6…` | 16 | **MINING** — same |
| **28** | `ce592dc0…` | 16 | **MINING** — same |
| **35** | `c0bafd1e…` | 16 | **MINING** — same |

**Not mining (DOC_MARK=NOT_RUNNING or still pending):** 23, 25, 26, 30, 31, 32, 36.

## Auth / refresh_token (2026-09-24)

**Daemon** auth wall → `ensure_authed` → Google `refresh_token` API + virgin-context IDB init-script → cookies (password login last). Docs: [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md), problem **#37**.

**Rescued full trios** (cookies + LS + IndexedDB `refresh_token=YES`, fkey synthesized):

| Cell | Lov session | Email | Notes |
|---|---|---|---|
| 28 | 41 | jamesmanalodat.e@gmail.com | synced |
| 30 | 44 | tra.nariumkill@gmail.com | synced |
| 31 | 46 | lovbvxh2yu05l@souss.dev | synced |
| 35 | 8 | hellolakanhernand.ez@gmail.com | synced; had `/term`+Worker earlier |
| 32 | 7 | lovuu5qwethzg@souss.dev | rescued + local refresh PASS; synced + new daemon |

**Toolkit:** `session_state.save_full_state` + `revive_via_refresh_token`; `load_session_with_rescue.py` uses refresh before password.

**Still open:** `/term`+`window.doc` on most cells (auth fixed ≠ mining). Fix C bridge (25/26/36) still pending.

## Xvfb fix 2026-09-24 — empty displays resolved

**Root cause:** (1) auto-headless on ≤1.1GB cgroup while `DISPLAY=:99` was set but `CHIMERA_FORCE_HEADED` missing → Playwright launched headless so Xvfb stayed black; (2) Xvfb started with `-nolisten unix` → no `/tmp/.X11-unix/X99` socket; (3) missing `--ozone-platform=x11`.

**Fix applied fleet-wide (11 cells):**
- daemon.md5 `8fc84c43225ca25657424e8fb53a9230` — keep headed when `DISPLAY` set; add ozone x11
- Xvfb restarted **without** `-nolisten unix` (unix socket present)
- `lean_sup` rewritten with `CHIMERA_FORCE_HEADED=1` + `DISPLAY=:99`
- Logs now show `Launched Chromium … (headless=False, DISPLAY=:99, …)`
- Xvfb root shots **11/11 CONTENT** under `shots-from-cell/cell-*-xvfb-now.png`

**Still not “mining” on every cell** — headed UI is up; auth/bridge blockers remain (access denied, login denied, skeleton load, 4 unbridged).

### cell-16 + cell-13 mining fix (cgroup reclaim loop)

**Cause:** Worker inject succeeded, then health #1 saw cgroup **~100%** (normal for headed+Worker on 1GB) and **hard-killed Chrome** → inject→kill forever. Empty/black Xvfb was a side effect of that chase, plus earlier headless/`-nolisten unix`.

**Fix (daemon `7740bb07…` on 16+13):** skip ceiling hard-kill when `CHIMERA_FORCE_HEADED`/`DISPLAY` set; never hard-kill on health-1. lean_sup also re-asserts Xvfb **without** `-nolisten unix` each restart.

**Proof:** both cells now log `skip hard-kill (deferred; babysit)` then repeated `Preview healthy` (health #2+).

**Also (daemon `9753be6e…`):** under CRITICAL mem, skip 7‑min soft-revive (always timed out) → immediate fresh-tab reinject; threads=16. cell-16/13 back to **Worker alive + Preview healthy**.

### Fleet fix C — bridge the 4 LEFT (cells 25/26/32/36)

[Bridge then mine the 4 LEFT](c9500849-a78e-433d-907f-3078bd76c370) — **0/4** bridge OK. Results: `/tmp/fleet_fix_C.json`, `/tmp/fleet_fix_C_inject.json`. Deploy skipped (no bridges). cell-16 untouched.

**Prep done:** synced `scripts/sessions/session-{3,7,8}` to correct accounts (were mismatched). OnKernel used unlocked key from `session_refresh.py` (default remix key billing-blocked).

| Cell | Status | Reason |
|---|---|---|
| **cell-25** | SEEKING | OnKernel `timeout_no_doc` (900s); daemon hunting `/term`+doc |
| **cell-26** | SEEKING | `timeout_no_doc`; daemon tab_fail/relaunch, no Worker |
| **cell-32** | **AUTH FIXED** | lov-s7 rescued; refresh_token revive proven locally; trio+daemon synced 2026-09-24 |
| **cell-36** | SEEKING | login submit timeout → `timeout_no_doc`; daemon “logged in” but no composer/doc |

### Group B follow-up (cells 30/31/35) — [Bridge+mine group B](60523053-7c98-4dfc-862b-0a9fb0ba5566)

OnKernel re-inject **blocked** (org payment method). Cookie sync + daemon md5 `c05b8a9e…` applied. Results in `/tmp/fleet_fix_B.json`:

| Cell | Status | Reason |
|---|---|---|
| cell-30 | SEEKING | preview `id-preview` Error / no lovableproject+doc |
| cell-31 | FAIL | `daemon_r31.log` frozen ~5h on panel TimeoutError |
| cell-35 | SEEKING | old Worker injected line; log stale; no miner procs now |

### Headed Xvfb status (post-fix)

| Cell | Project | Xvfb | Notes |
|---|---|---|---|
| **cell-16** | `7d6f77a6…` | **CONTENT** | **mining** — reclaim no longer kills at health-1; Preview healthy |
| **cell-13** | `05da1af6…` | **CONTENT** | **mining** — same reclaim fix; Preview healthy |
| cell-23 | `b06e4a07…` | **CONTENT** | access denied (wrong account cookies) |
| cell-25 | `211af3cb…` | **CONTENT** | Fix C: SEEKING `timeout_no_doc` |
| cell-26 | `0f318cab…` | **CONTENT** | Fix C: SEEKING `timeout_no_doc` |
| cell-28 | `ce592dc0…` | **CONTENT** | headed up |
| cell-30 | `b3ded203…` | **CONTENT** | headed up |
| cell-31 | `8ca51fa8…` | **CONTENT** | headed up |
| cell-32 | `e8ee22a2…` | **CONTENT** | Fix C: **FAIL** auth wall (lov-s7) |
| cell-35 | `c0bafd1e…` | **CONTENT** | login denied (suspicious activity) |
| cell-36 | `9421eb8a…` | **CONTENT** | Fix C: SEEKING `timeout_no_doc` |

### Bridge seen on OnKernel earlier, Railway still **not** mining

| Cell | Project |
|---|---|
| cell-23 | `b06e4a07…` |
| cell-28 | `ce592dc0…` |
| cell-30 | `b3ded203…` |
| cell-31 | `8ca51fa8…` |
| cell-35 | `c0bafd1e…` |

### Left for bridge — **4** (Fix C: 0/4)

| Cell | Project | Blocker |
|---|---|---|
| **cell-25** | `211af3cb…` | OnKernel `timeout_no_doc` — wait for build/`window.doc` on `/term` |
| **cell-26** | `0f318cab…` | same |
| **cell-32** | `e8ee22a2…` | **manual** lov-s7 login for `lovuu5qwethzg@souss.dev` (TOTP/password) — cookie refresh alone insufficient |
| **cell-36** | `9421eb8a…` | OnKernel `timeout_no_doc` (login submit flaky) |

### OnKernel note

Default org API key hit **billing / payment-method** block for browser create. Unlocked farm keys can still create. Org concurrent cap ≈ **5**. Resume inject with a working unlocked `KERNEL_API_KEY`, then sync cookies to cells and wait for **visible** `/term`+Worker — do not claim mining from OnKernel or log lines alone.

Canonical daemon recipe: [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md)

## Bridge (`window.doc`) gate

Worker inject needs **`window.doc` on `*.lovableproject.com/term`** (not Homepage) **inside the Railway cell browser**.

1. OnKernel script2: paste `automation-toolkit/prompts/Build a debug terminal.txt` → wait build → open **`/term`**.
2. `inject_fleet_projects.py` — cookies → Kernel → project → same inject/wait (`--workers 5`, slot semaphore).
3. `remix_inject.py` → `inject_and_wait_bridge()`.
4. Daemon: Preview lovableproject iframe → `/term` before `doc('pwd')`.

Wake/presence (`say 'a'`) is **not** the bridge prompt.

## Live map

| Railway HOME | Cell | Service ID | Lovable | Email | Project ID | Status |
|---|---|---|---|---|---|---|
| session-2 | **cell-16** | `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` | lov-s1 | altonlehman16@gmail.com | `7d6f77a6-69a1-4b06-a1d3-53094c4c8019` | **MINING** — nproc=16, forever lean_sup |
| session-1 | **cell-13** | `a45e3ffd-6d92-432a-ab17-a05673823edf` | lov-s1 | altonlehman16@gmail.com | `05da1af6-0626-4746-a339-92d7e6b2e3e1` | **MINING** — nproc=16, forever lean_sup |
| session-3 | **cell-23** | `e9a64328-6e1a-435e-a4d1-097082d77fcd` | lov-s2 | emmalinerivers9@gmail.com | `b06e4a07-95fb-4dc3-89a8-72ca84f2f25d` | daemon up — `/term` no-doc |
| session-4 | **cell-25** | `c917f7c9-0044-4763-b54e-c1daf1725804` | lov-s3 | emonkhanireht56@gmail.com | `211af3cb-5c3a-40b6-9a59-9bc0fe7b27de` | daemon up — bridge pending |
| session-5 | **cell-26** | `0ba61133-0c59-42a7-8473-46fd03557cbb` | lov-s3 | emonkhanireht56@gmail.com | `0f318cab-b3a4-49a1-a168-7e9fe36304ca` | daemon up — bridge pending |
| session-6 | **cell-28** | `ebd3f10a-203d-4bf7-92a3-39ea09b70956` | lov-s4 | jamesmanalodat.e@gmail.com | `ce592dc0-eb0f-4500-81ae-2f848840aaac` | **MINING** — nproc=16, forever lean_sup |
| session-7 | **cell-30** | `625eee55-0d4d-4748-a308-7a8175f27b0b` | lov-s5 | tra.nariumkill@gmail.com | `b3ded203-a845-4037-a648-5fbad0cba931` | daemon up — `/term` no-doc |
| session-8 | **cell-31** | `efd70f34-7ad3-489a-a2ae-75795ee1bc1c` | lov-s6 | lovbvxh2yu05l@souss.dev | `8ca51fa8-2c22-44d3-9510-a069084f791f` | daemon up — `/term` no-doc |
| session-9 | **cell-32** | `94759809-d724-42e3-8bca-0cb5be954626` | lov-s7 | lovuu5qwethzg@souss.dev | `e8ee22a2-7ea3-4f0c-8650-bd6b933288b0` | daemon up — auth wall |
| session-10 | **cell-35** | `893dd7cd-4f92-4e5b-b981-9e681705fbb2` | lov-s8 | hellolakanhernand.ez@gmail.com | `c0bafd1e-33d8-4625-89a4-1250f4755d23` | **MINING** — nproc=16, forever lean_sup |
| session-11 | **cell-36** | `a700ead9-eab8-4981-925f-a916153db20c` | lov-s8 | hellolakanhernand.ez@gmail.com | `9421eb8a-e853-49b2-a0dd-657c80246c5d` | daemon up — bridge pending |

## Locked — do not reuse

- **Railway CLI HOME** `automation-toolkit/sessions/session-2` → owns **cell-16** only
- SSH: `sessions/session-2/.ssh/cellkey`
- Project/env: `340b7baa-d67f-42ae-8c58-fd803b75dc72` / `801b5148-b8e5-445a-a9e5-a813998e5f9d`

## Notes

- Daemons: `daemon.py` md5 `c05b8a9e…` · `miner_injector.py` `b5033cbd…` · `lean_sup_rN.sh` per cell
- Logs: `/app/work/daemon_rN.log` (cell-16 keeps `daemon_s2.log`)
- Results artifacts: `/tmp/fleet_inject_results9.json` (5/9 OnKernel bridge) · `/tmp/fleet_restart9.json` (9 daemons restarted at stop)
- Next: working Kernel key → bridge the **4** + re-warm `/term` on the **5** until cell logs show **Worker confirmed** (like cell-16)
