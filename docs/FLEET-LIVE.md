# FLEET-LIVE — who is mining

**Updated:** 2026-09-23
**Rule:** one Railway cell per **Lovable project**. Accounts with 2 projects → 2 cells (same cookies, different `--project`).
**Railway order:** `session-1`, skip **`session-2`** (cell-16), then `session-3`…

Canonical daemon recipe: [`DAEMON-RAILWAY.md`](DAEMON-RAILWAY.md)

## Live map

| Railway HOME | Cell | Service ID | Lovable | Email | Project ID | Status |
|---|---|---|---|---|---|---|
| session-2 | **cell-16** | `46ab5f8c-b0c2-4e42-aab2-e055e5f61b1d` | lov-s1 | altonlehman16@gmail.com | `7d6f77a6-69a1-4b06-a1d3-53094c4c8019` | **mining** |
| session-1 | **cell-13** | `a45e3ffd-6d92-432a-ab17-a05673823edf` | lov-s1 | altonlehman16@gmail.com | `05da1af6-0626-4746-a339-92d7e6b2e3e1` | **mining** |
| session-3 | **cell-23** | `e9a64328-6e1a-435e-a4d1-097082d77fcd` | lov-s2 | emmalinerivers9@gmail.com | `b06e4a07-95fb-4dc3-89a8-72ca84f2f25d` | **mining** |
| session-4 | **cell-25** | `c917f7c9-0044-4763-b54e-c1daf1725804` | lov-s3 | emonkhanireht56@gmail.com | `211af3cb-5c3a-40b6-9a59-9bc0fe7b27de` | **mining** |
| session-5 | **cell-26** | `0ba61133-0c59-42a7-8473-46fd03557cbb` | lov-s3 | emonkhanireht56@gmail.com | `0f318cab-b3a4-49a1-a168-7e9fe36304ca` | **mining** |
| session-6 | **cell-28** | `ebd3f10a-203d-4bf7-92a3-39ea09b70956` | lov-s4 | jamesmanalodat.e@gmail.com | `ce592dc0-eb0f-4500-81ae-2f848840aaac` | **mining** |
| session-7 | **cell-30** | `625eee55-0d4d-4748-a308-7a8175f27b0b` | lov-s5 | tra.nariumkill@gmail.com | `b3ded203-a845-4037-a648-5fbad0cba931` | **mining** |
| session-8 | **cell-31** | `efd70f34-7ad3-489a-a2ae-75795ee1bc1c` | lov-s6 | lovbvxh2yu05l@souss.dev | `8ca51fa8-2c22-44d3-9510-a069084f791f` | **mining** |
| session-9 | **cell-32** | `94759809-d724-42e3-8bca-0cb5be954626` | lov-s7 | lovuu5qwethzg@souss.dev | `e8ee22a2-7ea3-4f0c-8650-bd6b933288b0` | **mining** |
| session-10 | **cell-35** | `893dd7cd-4f92-4e5b-b981-9e681705fbb2` | lov-s8 | hellolakanhernand.ez@gmail.com | `c0bafd1e-33d8-4625-89a4-1250f4755d23` | **mining** |
| session-11 | **cell-36** | `a700ead9-eab8-4981-925f-a916153db20c` | lov-s8 | hellolakanhernand.ez@gmail.com | `9421eb8a-e853-49b2-a0dd-657c80246c5d` | **mining** |

## Locked — do not reuse

- **Railway CLI HOME** `automation-toolkit/sessions/session-2` → owns **cell-16** only
- SSH: `sessions/session-2/.ssh/cellkey`
- Project/env: `340b7baa-d67f-42ae-8c58-fd803b75dc72` / `801b5148-b8e5-445a-a9e5-a813998e5f9d`

## Notes

- Daemons use local `daemon.py` md5 `c016f744…` (1GB Aw Snap path) + `lean_sup_rN.sh` on each cell
- Logs: `/app/work/daemon_rN.log` (cell-16 keeps `daemon_s2.log`)
- Expect 1GB babysit CRITICAL / reclaim loops — self-heal is normal

