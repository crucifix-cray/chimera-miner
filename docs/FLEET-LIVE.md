# FLEET-LIVE — who is mining

**Updated:** 2026-09-23  
**Rule:** one Railway cell per **Lovable project**. Accounts with 2 projects → 2 cells (same cookies, different `--project`).  
**Railway order:** `session-1`, skip **`session-2`** (cell-16), then `session-3`…

Canonical daemon recipe: [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md)

## Live / planned map

| Railway HOME | Cell service | Lovable scripts/sessions | Email | Project ID | Status |
|---|---|---|---|---|---|
| session-2 | **cell-16** `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` | lov-s1 (alton) | altonlehman16@gmail.com | `7d6f77a6-69a1-4b06-a1d3-53094c4c8019` | **mining** |
| session-1 | cell-13 `a45e3ffd-6d92-432a-ab17-a05673823edf` | lov-s1 (alton) | altonlehman16@gmail.com | `05da1af6-0626-4746-a339-92d7e6b2e3e1` | pending |
| session-3 | *(from cells.json)* | lov-s2 | emmalinerivers9@gmail.com | `b06e4a07-95fb-4dc3-89a8-72ca84f2f25d` | pending |
| session-4 | | lov-s3 | emonkhanireht56@gmail.com | `211af3cb-5c3a-40b6-9a59-9bc0fe7b27de` | pending |
| session-5 | | lov-s3 | emonkhanireht56@gmail.com | `0f318cab-b3a4-49a1-a168-7e9fe36304ca` | pending |
| session-6 | | lov-s4 | jamesmanalodat.e@gmail.com | `ce592dc0-eb0f-4500-81ae-2f848840aaac` | pending |
| session-7 | | lov-s5 | tra.nariumkill@gmail.com | `b3ded203-a845-4037-a648-5fbad0cba931` | pending |
| session-8 | | lov-s6 | lovbvxh2yu05l@souss.dev | `8ca51fa8-2c22-44d3-9510-a069084f791f` | pending |
| session-9 | | lov-s7 | lovuu5qwethzg@souss.dev | `e8ee22a2-7ea3-4f0c-8650-bd6b933288b0` | pending |
| session-10 | | lov-s8 | hellolakanhernand.ez@gmail.com | `c0bafd1e-33d8-4625-89a4-1250f4755d23` | pending |
| session-11 | | lov-s8 | hellolakanhernand.ez@gmail.com | `9421eb8a-e853-49b2-a0dd-657c80246c5d` | pending |

## Locked — do not reuse

- **Railway CLI HOME** `automation-toolkit/sessions/session-2` → owns cell-16 only  
- SSH: `sessions/session-2/.ssh/cellkey`  
- Project/env: `340b7baa…` / `801b5148…`

## Status legend

- **mining** — daemon + lean_sup up, workers confirmed  
- **pending** — cell exists or planned; daemon not verified yet  
- **dead** — account/login broken; removed from active fleet  

When a row flips to mining, update this file and push to `master`.
