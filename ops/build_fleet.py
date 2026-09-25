#!/usr/bin/env python3
"""Build ops/fleet.json — the ONE live registry (cells + sessions + trio health).

Sources (read-only): local daemon/miner md5, toolkit services.json,
fleet_map.json (legacy mining overlay), disk trios, FLEET-LIVE pending map.
Usage: python3 ops/build_fleet.py
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = Path(__file__).resolve().parent
ATK = Path("/home/alae/Documents/repos/automation-toolkit")
SESS = ATK / "scripts/sessions"

# Sessions fully loaded (project + live /term bridge + trio): ready for a cell.
READY = {
    25: (None, "84fa81b7-6c8d-45ab-95a8-7e89bbf92864", "project+bridge ready, needs cell"),
}

# Pending cells: Railway sess -> (lov session, Lovable project, note) per docs/FLEET-LIVE.md
PENDING = {
    23: (7, "b06e4a07-95fb-4dc3-89a8-72ca84f2f25d", "bare image, trio ready"),
    25: (8, "211af3cb-5c3a-40b6-9a59-9bc0fe7b27de", "bare image, trio ready"),
    26: (8, "0f318cab-b3a4-49a1-a168-7e9fe36304ca", "bare image, trio ready (shared sess-8)"),
    30: (44, "b3ded203-a845-4037-a648-5fbad0cba931", "bare image, trio ready -- NEXT CANDIDATE"),
    31: (46, "8ca51fa8-2c22-44d3-9510-a069084f791f", "bare image, trio ready"),
    32: (48, "e8ee22a2-7ea3-4f0c-8650-bd6b933288b0", "bare image, trio INCOMPLETE needs rescue"),
    36: (50, "9421eb8a-e853-49b2-a0dd-657c80246c5d", "bare image, trio ready (shared sess-50)"),
}

# Live mining cells not in legacy fleet_map (verified via cell_ops status)
MINING_EXTRA = {
    43: (25, "84fa81b7-6c8d-45ab-95a8-7e89bbf92864", "daemon_r43.log"),
    # 2026-09-25 17:55 UTC — verified `Worker alive` + `Preview healthy`
    53: (25, "84fa81b7-6c8d-45ab-95a8-7e89bbf92864", "daemon_r53.log"),
    76: (26, "e474f21d-256c-4de6-95c9-06a53eec87dc", "daemon_r76.log"),
    77: (27, "cdcc177a-5e4c-42ac-8256-c4acf1040034", "daemon_r77.log"),
    81: (30, "9f42ef89-ed41-4b5f-af7f-f8e1554378c4", "daemon_r81.log"),
    83: (37, "1f5b8636-b2b4-45f0-9375-e81389f79d21", "daemon_r83.log"),
    87: (40, "ac03f128-3500-4ecf-9d9b-8efb352b530e", "daemon_r87.log"),
    88: (42, "388ebccb-c73d-48b3-880d-a99517afd855", "daemon_r88.log"),
    89: (43, "f16469dc-1747-4cb7-bb79-d676b904e4be", "daemon_r89.log"),
}


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def trio_health(d: Path) -> dict:
    out = {"cookies": False, "localstorage": False, "indexeddb": False, "refresh_token": False}
    if (d / "cookies.json").exists():
        out["cookies"] = True
    if (d / "localstorage.json").exists():
        out["localstorage"] = True
    idb = d / "indexeddb.json"
    if idb.exists():
        out["indexeddb"] = True
        try:
            b = idb.read_text()
            out["refresh_token"] = "refreshToken" in b or "refresh_token" in b
        except Exception:
            pass
    return out


def main() -> int:
    legacy_cells: dict = {}
    if (OPS / "fleet_map.json").exists():
        legacy_cells = json.loads((OPS / "fleet_map.json").read_text()).get("cells", {})
    elif (OPS / "fleet.json").exists():
        prev = json.loads((OPS / "fleet.json").read_text())
        for n, c in prev.get("cells", {}).items():
            if c.get("miner") == "mining":
                legacy_cells[n] = {"lov_session": c.get("lov_session"),
                                   "project": c.get("lovable_project"),
                                   "log": c.get("log")}
    services = []
    if (ATK / "services.json").exists():
        services = json.loads((ATK / "services.json").read_text())
    for src in (SESS / "invites.json",
                ATK / "_archived_registry_20260925" / "invites.json"):
        try:
            invites = json.load(open(src))
            break
        except Exception:
            invites = []
    if not invites and (OPS / "fleet.json").exists():
        try:
            invites = json.loads((OPS / "fleet.json").read_text())["meta"].get("known_invites", [])
        except Exception:
            pass

    cells: dict[str, dict] = {}
    if (ATK / "services.json").exists():
        services = json.loads((ATK / "services.json").read_text())
        for s in services:
            svc = s.get("service", "")
            if not svc.startswith("cell-"):
                continue
            n = svc.split("-", 1)[1]
            cells[n] = {
                "railway_session": int(str(s["session"]).replace("session-", "")),
                "service": svc,
                "railway_project": s.get("project"),
                "env": s.get("env"),
                "volume": s.get("volume"),
                "service_status": s.get("status"),
                "lov_session": None,
                "lovable_project": None,
                "log": None,
                "miner": "unknown",
            }
    elif (OPS / "fleet.json").exists():
        for n, c in json.loads((OPS / "fleet.json").read_text()).get("cells", {}).items():
            cells[n] = {k: c.get(k) for k in (
                "railway_session", "service", "railway_project", "env",
                "volume", "service_status", "lov_session", "lovable_project",
                "log", "miner", "note")}
            if cells[n].get("miner") != "mining":
                cells[n]["lov_session"] = None
                cells[n]["lovable_project"] = None
                cells[n]["miner"] = "unknown"
                cells[n].pop("note", None)
    for n, info in legacy_cells.items():
        c = cells.setdefault(n, {})
        if info.get("lov_session") is not None:
            c["lov_session"] = int(info["lov_session"])
        if info.get("project"):
            c["lovable_project"] = info["project"]
        c["log"] = info.get("log", f"daemon_r{n}.log")
        c["miner"] = "mining"
        c.setdefault("railway_session", info.get("railway_session"))
        c.setdefault("service", info.get("service_name", f"cell-{n}"))
    for n, (lov, proj, log) in MINING_EXTRA.items():
        c = cells.setdefault(str(n), {})
        c["lov_session"] = lov
        c["lovable_project"] = proj
        c["log"] = log
        c["miner"] = "mining"
    for n, (lov, proj, note) in PENDING.items():
        c = cells.setdefault(str(n), {})
        c["lov_session"] = lov
        c["lovable_project"] = proj
        c["miner"] = "bare"
        c["note"] = note
    # ops/assign_plan.json: bridged session -> healthy cell. Cells already in
    # the mining map keep their state; the rest are "assigned".
    plan_path = OPS / "assign_plan.json"
    if plan_path.exists():
        for e in json.loads(plan_path.read_text()):
            n = str(e["cell"])
            c = cells.setdefault(n, {})
            if c.get("miner") == "mining":
                continue
            c["lov_session"] = int(e["lov"])
            c["lovable_project"] = e["project"]
            c["log"] = f"daemon_r{n}.log"
            c["miner"] = "assigned"
            c.pop("note", None)

    sessions: dict[str, dict] = {}
    for d in sorted(SESS.iterdir()):
        if not (d.is_dir() and d.name.startswith("session-")) or not d.name.split("-")[1].isdigit():
            continue
        try:
            cfg = json.load(open(d / "config.json"))
            email = cfg.get("email", "?")
        except Exception:
            email = "?"
            cfg = {}
        t = trio_health(d)
        full = all(t.values())
        token_email = None
        try:
            for r in json.loads((d / "indexeddb.json").read_text()):
                v = r.get("value") if isinstance(r, dict) else None
                if isinstance(v, dict) and (v.get("stsTokenManager") or {}).get("refreshToken"):
                    token_email = v.get("email")
                    break
        except Exception:
            pass
        sessions[d.name] = {"email": email, "token_email": token_email,
                            "identity_ok": bool(token_email) and token_email.casefold() == (email or "").casefold(),
                            "trio": t, "full": full,
                            "status": "bench", "cells": [],
                            "project_id": cfg.get("project_id"),
                            "project_link": cfg.get("project_link"),
                            "invite_link": cfg.get("invite_link")}
    for n, c in cells.items():
        if c.get("miner") in ("mining", "assigned") and c.get("lov_session") is not None:
            key = f"session-{c['lov_session']}"
            if key in sessions:
                if c["miner"] == "mining" or sessions[key]["status"] != "mining":
                    sessions[key]["status"] = c["miner"]
                sessions[key]["cells"].append(int(n))
    for n, (lov, _proj, note) in PENDING.items():
        key = f"session-{lov}"
        if key in sessions and sessions[key]["status"] == "bench" and "needs rescue" not in note:
            sessions[key]["status"] = "assigned-bare"
            sessions[key]["cells"].append(int(n))
    for lov, (_cell, proj, note) in READY.items():
        key = f"session-{lov}"
        if key in sessions:
            sessions[key]["status"] = "ready-to-mine"
            sessions[key]["ready_note"] = note
            if proj and not sessions[key].get("project_id"):
                sessions[key]["project_id"] = proj

    mining = sorted({c["lov_session"] for c in cells.values() if c.get("miner") == "mining"})
    bench = sorted([k for k, v in sessions.items() if v["status"] == "bench"])
    # fixed rig per cell (threads/bridge baked into lean_sup; preserved across rebuilds)
    prev_rigs = {}
    if (OPS / "fleet.json").exists():
        try:
            prev_rigs = {n: c.get("rig") for n, c in
                         json.loads((OPS / "fleet.json").read_text()).get("cells", {}).items()
                         if c.get("rig")}
        except Exception:
            pass
    for n, c in cells.items():
        c["rig"] = prev_rigs.get(n) or {"threads": 16, "bridge": ""}

    fleet = {
        "meta": {
            "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "daemon_md5": md5(ROOT / "daemon.py"),
            "injector_md5": md5(ROOT / "miner_injector.py"),
            "bridge": "wss://chimera-bridge-production-0703.up.railway.app",
            "known_invites": invites,
            "counts": {"cells": len(cells),
                       "sessions": len(sessions),
                       "mining_cells": sum(1 for c in cells.values() if c.get("miner") == "mining"),
                       "bench": len(bench)},
        },
        "cells": cells,
        "sessions": sessions,
        "mining_lov_sessions": [f"session-{m}" for m in mining],
        "bench": bench,
    }
    out = OPS / "fleet.json"
    out.write_text(json.dumps(fleet, indent=2) + "\n")
    print(f"wrote {out} cells={len(cells)} sessions={len(sessions)} bench={len(bench)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
