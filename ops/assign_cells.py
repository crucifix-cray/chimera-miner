#!/usr/bin/env python3
"""Assign bridged sessions to free cells + write the plan (no deploys)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, "ops")
from cell_ops import load_map  # noqa

FLEET = Path("ops/fleet.json")

# cell-75/95/110/120 live on Railway workspaces that are payment-restricted
# -> no new deploys. Excluded until a payment method is attached.
BLOCKED = {"75", "95", "110", "120"}
# already mining
MINING = {"13", "16", "28", "35", "43"}


def main() -> int:
    fmap = load_map()
    fleet = json.loads(FLEET.read_text())
    cells = fleet["cells"]
    sessions = fleet["sessions"]

    # bridged = has project_id and not already mining
    ready = []
    for name, s in sessions.items():
        if not s.get("project_id"):
            continue
        if s["status"] == "mining":
            continue
        ready.append((int(name.split("-")[1]), name, s["project_id"], s["email"]))
    ready.sort()

    free = [n for n, c in cells.items()
            if c.get("miner") == "unknown" and n not in BLOCKED and n not in MINING]
    free.sort(key=int)

    print(f"ready sessions: {len(ready)}  free cells: {len(free)}")
    plan = []
    for (num, name, proj, email), cell in zip(ready, free):
        plan.append({"cell": int(cell), "lov": num, "session": name,
                     "project": proj, "email": email})
        print(f"cell-{cell} <- {name} ({email}) {proj[:8]}")
    Path("ops/assign_plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    leftover_c = len(free) - len(ready)
    leftover_s = len(ready) - len(free)
    print(f"unassigned cells: {leftover_c}  sessions without a cell: {leftover_s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
