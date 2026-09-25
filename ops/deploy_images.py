#!/usr/bin/env python3
"""Deploy cell_service image to a batch of free Railway cells (raw IP, detached).

Usage: python3 ops/deploy_images.py 53 75 76 ...
Reads the Railway CLI HOME from ops/fleet.json cells[N].railway_session,
stages Dockerfile+start.sh into the linked dir, runs `railway up --detach`.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cell_ops import ATK_RW, load_map  # noqa

IMG = Path("/home/alae/Documents/repos/automation-toolkit/scripts/cell_service")
PROXY = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy", "LD_PRELOAD"]


def linked_dir(home: Path, service_name: str) -> Path | None:
    cfg = json.loads((home / ".railway" / "config.json").read_text())
    for k, v in cfg.get("projects", {}).items():
        if v.get("name") == service_name:
            return Path(k)
    return None


def deploy(cell: int, fmap: dict) -> tuple[int, str]:
    c = fmap["cells"][str(cell)]
    home = ATK_RW / f"session-{c['railway_session']}"
    svc = c["service"]
    d = linked_dir(home, svc)
    if not d:
        return cell, f"no linked dir for {svc}"
    d.mkdir(parents=True, exist_ok=True)
    (d / ".railway").mkdir(exist_ok=True)
    shutil.copy(home / ".railway" / "config.json", d / ".railway" / "config.json")
    for f in ("Dockerfile", "start.sh"):
        shutil.copy(IMG / f, d / f)
    env = {**__import__("os").environ, "HOME": str(home)}
    for k in PROXY:
        env.pop(k, None)
    env.pop("RAILWAY_TOKEN", None)
    p = subprocess.run(
        ["railway", "up", "-s", svc, "-y", "--detach"],
        cwd=d, env=env, capture_output=True, text=True, timeout=300,
    )
    tail = (p.stdout or "")[-200:] + (p.stderr or "")[-200:]
    return cell, f"rc={p.returncode} {tail.strip()[:180]}"


def main() -> int:
    cells = [int(x) for x in sys.argv[1:]]
    fmap = load_map()
    for cell in cells:
        n, msg = deploy(cell, fmap)
        print(f"cell-{n}: {msg}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
