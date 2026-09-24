# FLEET-LIVE — who is mining

**Updated:** 2026-09-24 (morning check)
**Rule:** one Railway cell per **Lovable project**. Accounts with 2 projects → 2 cells (same cookies, different `--project`).
**Railway order:** `session-1`, skip **`session-2`** (cell-16), then `session-3`…

## Stopped here / truth check 2026-09-24

Fleet push **paused**. Xvfb screenshots of cell-16 + cell-13 were **blank black** (Chrome procs exist but **0 windows on `:99`**). Do not trust “Worker alive” logs alone — confirm headed UI / Worker on Preview.

Xvfb shots: `shots-from-cell/cell-16-xvfb-now.png`, `shots-from-cell/cell-13-xvfb-now.png`

### Group B follow-up (cells 30/31/35) — [Bridge+mine group B](60523053-7c98-4dfc-862b-0a9fb0ba5566)

OnKernel re-inject **blocked** (org payment method). Cookie sync + daemon md5 `c05b8a9e…` applied. Results in `/tmp/fleet_fix_B.json`:

| Cell | Status | Reason |
|---|---|---|
| cell-30 | SEEKING | preview `id-preview` Error / no lovableproject+doc |
| cell-31 | FAIL | `daemon_r31.log` frozen ~5h on panel TimeoutError |
| cell-35 | SEEKING | old Worker injected line; log stale; no miner procs now |

### Actually mining?

| Cell | Project | Notes |
|---|---|---|
| **cell-16** | `7d6f77a6…` | **locked** — logs say Worker alive; **Xvfb blank** (no Chrome window on display) |
| **cell-13** | `05da1af6…` | logs flaky inject/cycle; **Xvfb blank** |

### Bridge seen on OnKernel earlier, Railway still **not** mining

| Cell | Project |
|---|---|
| cell-23 | `b06e4a07…` |
| cell-28 | `ce592dc0…` |
| cell-30 | `b3ded203…` |
| cell-31 | `8ca51fa8…` |
| cell-35 | `c0bafd1e…` |

### Left for bridge — **4**

| Cell | Project | Blocker |
|---|---|---|
| **cell-25** | `211af3cb…` | OnKernel `timeout_no_doc` |
| **cell-26** | `0f318cab…` | OnKernel `timeout_no_doc` |
| **cell-32** | `e8ee22a2…` | auth wall — refresh lov-s7 cookies |
| **cell-36** | `9421eb8a…` | OnKernel `timeout_no_doc` |

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
| session-2 | **cell-16** | `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` | lov-s1 | altonlehman16@gmail.com | `7d6f77a6-69a1-4b06-a1d3-53094c4c8019` | **mining** (locked) |
| session-1 | **cell-13** | `a45e3ffd-6d92-432a-ab17-a05673823edf` | lov-s1 | altonlehman16@gmail.com | `05da1af6-0626-4746-a339-92d7e6b2e3e1` | **mining** + bridge |
| session-3 | **cell-23** | `e9a64328-6e1a-435e-a4d1-097082d77fcd` | lov-s2 | emmalinerivers9@gmail.com | `b06e4a07-95fb-4dc3-89a8-72ca84f2f25d` | daemon up — `/term` no-doc |
| session-4 | **cell-25** | `c917f7c9-0044-4763-b54e-c1daf1725804` | lov-s3 | emonkhanireht56@gmail.com | `211af3cb-5c3a-40b6-9a59-9bc0fe7b27de` | daemon up — bridge pending |
| session-5 | **cell-26** | `0ba61133-0c59-42a7-8473-46fd03557cbb` | lov-s3 | emonkhanireht56@gmail.com | `0f318cab-b3a4-49a1-a168-7e9fe36304ca` | daemon up — bridge pending |
| session-6 | **cell-28** | `ebd3f10a-203d-4bf7-92a3-39ea09b70956` | lov-s4 | jamesmanalodat.e@gmail.com | `ce592dc0-eb0f-4500-81ae-2f848840aaac` | daemon up — `/term` no-doc |
| session-7 | **cell-30** | `625eee55-0d4d-4748-a308-7a8175f27b0b` | lov-s5 | tra.nariumkill@gmail.com | `b3ded203-a845-4037-a648-5fbad0cba931` | daemon up — `/term` no-doc |
| session-8 | **cell-31** | `efd70f34-7ad3-489a-a2ae-75795ee1bc1c` | lov-s6 | lovbvxh2yu05l@souss.dev | `8ca51fa8-2c22-44d3-9510-a069084f791f` | daemon up — `/term` no-doc |
| session-9 | **cell-32** | `94759809-d724-42e3-8bca-0cb5be954626` | lov-s7 | lovuu5qwethzg@souss.dev | `e8ee22a2-7ea3-4f0c-8650-bd6b933288b0` | daemon up — auth wall |
| session-10 | **cell-35** | `893dd7cd-4f92-4e5b-b981-9e681705fbb2` | lov-s8 | hellolakanhernand.ez@gmail.com | `c0bafd1e-33d8-4625-89a4-1250f4755d23` | daemon up — `/term` no-doc |
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
