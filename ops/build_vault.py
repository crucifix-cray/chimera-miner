#!/usr/bin/env python3
"""Build ops/vault.json — ONE credentials+state vault for all live sessions.

Per session: email, password, 2FA secrets, linked projects/cells (from
fleet.json), and the full stored trio (cookies, localstorage, indexeddb
with Firebase refresh_token).

SECRET FILE — lives next to fleet.json, git-ignored by default decision
of the operator. Rebuild: python3 ops/build_vault.py
"""
from __future__ import annotations

import datetime
import json
from pathlib import Path

OPS = Path(__file__).resolve().parent
ATK = Path("/home/alae/Documents/repos/automation-toolkit")
SESS = ATK / "scripts/sessions"


def load(p: Path):
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def main() -> int:
    fleet = json.loads((OPS / "fleet.json").read_text())
    # cell usage per lov session: {lovable_project, cell, miner}
    use: dict[str, list] = {}
    for n, c in fleet.get("cells", {}).items():
        lov = c.get("lov_session")
        if lov is None or not c.get("lovable_project"):
            continue
        use.setdefault(f"session-{lov}", []).append({
            "cell": int(n),
            "lovable_project": c["lovable_project"],
            "miner": c.get("miner", "unknown"),
        })

    vault: dict[str, dict] = {}
    for name in sorted(fleet.get("sessions", {})):
        d = SESS / name
        cfg = load(d / "config.json") or {}
        cookies = load(d / "cookies.json")
        ls = load(d / "localstorage.json")
        idb = load(d / "indexeddb.json")
        rt = False
        if idb is not None:
            b = json.dumps(idb)
            rt = "refreshToken" in b or "refresh_token" in b
        vault[name] = {
            "email": cfg.get("email"),
            "password": cfg.get("password"),
            "totp_secret": cfg.get("totp_secret"),
            "totp_secret_backup": cfg.get("totp_secret_backup"),
            "2fa_live_id": cfg.get("2fa_live_id"),
            "dashboard_url": cfg.get("dashboard_url"),
            "account_status": cfg.get("status"),
            "verified": cfg.get("verified"),
            "projects": use.get(name, []),
            "has_refresh_token": rt,
            "cookies": cookies,
            "localstorage": ls,
            "indexeddb": idb,
        }

    out = {
        "meta": {
            "updated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sessions": len(vault),
            "note": "SECRET — credentials + full trios + linked projects. Do not publish.",
        },
        "sessions": vault,
    }
    p = OPS / "vault.json"
    p.write_text(json.dumps(out, indent=1))
    print(f"wrote {p} {p.stat().st_size} bytes sessions={len(vault)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
