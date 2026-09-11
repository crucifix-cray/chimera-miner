#!/usr/bin/env python3
"""Script 4: rotate miners across 10 Lovable projects (supervisor).

Strict 1->10 order per round. Each visit spawns:
  script3_launch_miner.py --mode oneshot --project PID --session N
(same-tab chat->prompt->settle->preview->console-ready gate->inject->pgrep verify),
then --dwell human presence, then next. Round 1 dwell=30s (speedrun),
round 2+ dwell=180s (patrol). Fails tracked in /tmp/script4_progress.json,
2x fails -> --deep visit (2x budget). Scoreboard: grep "round done".

Usage:
  python3 script4_rotate_miners.py --session 1 [--rounds 2] [--dwell2 180]
  MINER_CMD='...' python3 script4_rotate_miners.py --session 1 --rounds 0  # infinite patrol
Env: raw IP (proxy vars stripped), LD_PRELOAD='', DISPLAY=:0, CHIMERA_NO_MEGA=1.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT3 = HERE / "script3_launch_miner.py"
PROGRESS = Path("/tmp/script4_progress.json")
STARTUP_TIMEOUT = 300  # browser+login+prompt+settle+preview+inject budget per visit
DEEP_MULT = 2


def base_env():
    e = dict(os.environ, LD_PRELOAD="")
    e["CHIMERA_NO_MEGA"] = "1"
    e["PROXY_PORT"] = "9"  # force direct; WARP :40000 is dead (Host unreachable)
    e.setdefault("DISPLAY", ":0")
    e.setdefault("CHIMERA_SESSIONS_DIR",
                 "/home/alae/Documents/repos/automation-toolkit/scripts/sessions")
    e.setdefault("CHIMERA_TOOLKIT_CORE",
                 "/home/alae/Documents/repos/automation-toolkit/finals/core")
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy",
              "https_proxy", "all_proxy"):
        e.pop(k, None)
    return e


def default_projects(session):
    """First 10 linked projects from the session's verify file (strict order)."""
    cands = [
        Path(f"/home/alae/Documents/repos/automation-toolkit/finals/verify_session-{session}.json"),
    ]
    for c in cands:
        if c.exists():
            try:
                items = json.loads(c.read_text())
                ids = [p["project_id"] for p in items if p.get("linked")]
                if len(ids) >= 10:
                    return ids[:10]
                if ids:
                    return ids
            except Exception:
                continue
    return []


def load_progress():
    try:
        return json.loads(PROGRESS.read_text())
    except Exception:
        return {"fails": {}, "verified": []}


def save_progress(p):
    PROGRESS.write_text(json.dumps(p, indent=2))


def pgrep_sysoptd():
    """Truth check: use [s]ysoptd self-match-safe pattern via pgrep -f."""
    try:
        out = subprocess.run(["pgrep", "-f", "[s]ysoptd"],
                             capture_output=True, text=True, timeout=10)
        return [l for l in out.stdout.split() if l.strip()]
    except Exception:
        return []


def visit(session, pid, tag, dwell, deep=False, timeout=None):
    """One supervised visit. Returns (verified: bool, note: str)."""
    budget = timeout or (STARTUP_TIMEOUT + dwell + 240)
    if deep:
        budget *= DEEP_MULT
    logf = f"/tmp/script3_{tag}.log"
    cmd = [sys.executable, "-u", str(SCRIPT3), "--session", str(session),
           "--mode", "oneshot", "--project", pid]
    print(f"[{tag}] visit {pid} dwell={dwell}s budget={budget}s deep={deep}", flush=True)

    def _log_verified():
        try:
            out = open(logf, errors="replace").read()
            return ("Worker is running" in out) or ("Preview healthy" in out)
        except Exception:
            return False

    try:
        with open(logf, "w") as lf:
            proc = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT,
                                  timeout=budget, env=base_env())
        out = open(logf, errors="replace").read()
        verified = ("Worker is running" in out) or ("VERIFIED" in out) or bool(pgrep_sysoptd())
        # dwell = human presence on the preview (only if verified)
        if verified and dwell > 0:
            print(f"[{tag}] dwell {dwell}s (presence)...", flush=True)
            time.sleep(dwell)
            if not pgrep_sysoptd():
                return False, "ok-dwell-cut (miner gone after dwell)"
        return verified, ("verified" if verified else "no-verify")
    except subprocess.TimeoutExpired:
        # budget kill on a healthy long patrol still means inject worked
        if _log_verified():
            return True, "ok-dwell-cut (verified before budget hit)"
        return False, "ok-dwell-cut (visit budget hit, unverified)"
    except Exception as e:
        return False, f"error: {e}"[:200]


def main():
    ap = argparse.ArgumentParser(description="Script 4: rotate miners over 10 projects")
    ap.add_argument("--session", required=True)
    ap.add_argument("--projects", default="", help="comma-separated project IDs (default: first 10 linked from verify file)")
    ap.add_argument("--rounds", type=int, default=2, help="rounds to run (0 = infinite patrol)")
    ap.add_argument("--dwell1", type=int, default=30, help="round-1 dwell seconds (speedrun)")
    ap.add_argument("--dwell2", type=int, default=180, help="round-2+ dwell seconds (patrol)")
    a = ap.parse_args()

    pids = [p.strip() for p in a.projects.split(",") if p.strip()] or default_projects(a.session)
    if len(pids) < 10:
        print(f"⚠️  only {len(pids)} projects (want 10) — continuing anyway")
    else:
        pids = pids[:10]
    if not pids:
        print("❌ no projects — run script3 --mode verify first")
        sys.exit(2)
    print(f"Projects 1..{len(pids)}: {', '.join(p[:8] for p in pids)}")

    prog = load_progress()
    fails = prog.setdefault("fails", {})
    verified_all = set(prog.setdefault("verified", []))
    rnd = 0
    while True:
        rnd += 1
        dwell = a.dwell1 if rnd == 1 else a.dwell2
        print(f"\n===== ROUND {rnd} (dwell={dwell}s) =====", flush=True)
        for i, pid in enumerate(pids, 1):
            tag = f"{pid[:8]}"
            ok, note = visit(a.session, pid, tag, dwell)
            key = f"{a.session}:{pid}"
            if ok:
                fails.pop(key, None)
                verified_all.add(key)
                print(f"✅ #{i} {pid[:8]} VERIFIED ({note})", flush=True)
            else:
                fails[key] = fails.get(key, 0) + 1
                print(f"❌ #{i} {pid[:8]} fail x{fails[key]} ({note})", flush=True)
                if fails[key] >= 2:
                    print(f"🔁 #{i} {pid[:8]} --deep visit", flush=True)
                    ok2, note2 = visit(a.session, pid, tag + "deep", dwell, deep=True)
                    if ok2:
                        fails.pop(key, None)
                        verified_all.add(key)
                        print(f"✅ #{i} {pid[:8]} VERIFIED-deep", flush=True)
            prog["fails"] = fails
            prog["verified"] = sorted(verified_all)
            save_progress(prog)
        print(f"--- round done ({rnd}): {len(verified_all)} verified total ---", flush=True)
        if a.rounds and rnd >= a.rounds:
            break
    print(f"DONE: {len(verified_all)} verified: {sorted(verified_all)}")


if __name__ == "__main__":
    main()
