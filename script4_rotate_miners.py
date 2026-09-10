#!/usr/bin/env python3
"""
Script 4: 10-project rotation SUPERVISOR.

Does ZERO browser work itself. Each visit = one `script3_launch_miner.py`
oneshot run (the proven flow: chat -> prompt -> preview -> console-wait ->
inject -> verify). Supervisor gives it time to VERIFY, adds human-presence
dwell, kills it, moves to the next project. Loops forever.

Miners persist server-side; killing the browser never stops them.

Usage:
  MINER_CMD='...' python3 -u script4_rotate_miners.py \
    --session 1 --threads 64 --dwell 240 \
    --projects 9941886d-...,55e09bdc-...,...
"""
import argparse
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).parent
SCRIPT3 = HERE / "script3_launch_miner.py"

# script3 needs up to ~9 min worst case (console-wait 5 + inject 2 + overhead)
STARTUP_TIMEOUT = 720
POLL = 10


def run_visit(pid: str, tag: str, session: str, threads: int, dwell: int,
              env: dict) -> str:
    """Run script3 oneshot for one project. Returns status string."""
    logf = f"/tmp/script3_{tag}.log"
    # fresh log per visit
    try:
        os.remove(logf)
    except OSError:
        pass
    cmd = [sys.executable, "-u", str(SCRIPT3),
           "--session", session, "--mode", "oneshot", "--db", "local",
           "--project", pid, "--threads", str(threads)]
    print(f"[{tag}] 🚀 starting script3...", flush=True)
    lf = open(logf, "a")
    proc = subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env,
                            start_new_session=True)
    try:
        verified = False
        waited = 0
        while waited < STARTUP_TIMEOUT:
            time.sleep(POLL)
            waited += POLL
            if proc.poll() is not None:
                print(f"[{tag}] ⚠️ script3 exited early (code {proc.returncode})",
                      flush=True)
                break
            try:
                tail = open(logf, errors="replace").read()[-4000:]
            except OSError:
                continue
            if "Worker VERIFIED" in tail or "VERIFIED running" in tail:
                verified = True
                print(f"[{tag}] ✅ VERIFIED — presence dwell {dwell}s...",
                      flush=True)
                break
            if "no chat input" in tail[-1500:] and waited > 240:
                print(f"[{tag}] ⚠️ still no chat input after 4 min...", flush=True)
        if verified:
            # human presence: let the proven run sit on the pages
            time.sleep(dwell)
            status = "ok"
        else:
            # last chance: check the tail for a late verify
            try:
                tail = open(logf, errors="replace").read()[-4000:]
            except OSError:
                tail = ""
            if "Worker VERIFIED" in tail or "VERIFIED running" in tail:
                status = "ok-late"
            else:
                status = "no-verify"
                print(f"[{tag}] ❌ never verified this visit", flush=True)
    finally:
        # kill the whole process group (browser + driver included)
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            pass
        try:
            proc.wait(timeout=15)
        except Exception:
            pass
        lf.close()
    return status


def main():
    ap = argparse.ArgumentParser(description="Script 4 supervisor")
    ap.add_argument("--session", required=True)
    ap.add_argument("--projects", required=True)
    ap.add_argument("--threads", type=int, default=64)
    ap.add_argument("--dwell", type=int, default=30,
                    help="Presence seconds AFTER verify (default 30: confirm it holds, move on)")
    args = ap.parse_args()

    pids = [p.strip() for p in args.projects.split(",") if p.strip()]
    print(f"🔄 SCRIPT 4 SUPERVISOR: {len(pids)} projects, "
          f"dwell {args.dwell}s, threads {args.threads}", flush=True)

    env = dict(os.environ)
    env.pop("HEADLESS", None)  # headed: operator watches, proven path
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy"):
        env.pop(v, None)
    env["LD_PRELOAD"] = ""
    if not env.get("DISPLAY"):
        env["DISPLAY"] = ":0"

    # resume progress across restarts: every relaunch used to restart at
    # project 1, starving 3-10. Persist next index + round to disk.
    import json as _json
    progress_file = "/tmp/script4_progress.json"
    try:
        _prog = _json.load(open(progress_file))
        start_idx = int(_prog.get("next_idx", 0)) % len(pids)
        round_n = int(_prog.get("round", 1))
        print(f"📌 resuming: round {round_n}, starting at #{start_idx+1} "
              f"({pids[start_idx][:8]})", flush=True)
    except Exception:
        start_idx, round_n = 0, 1
    results = {}
    first_round = True
    while True:
        if not first_round:
            start_idx = 0
        first_round = False
        print(f"\n{'='*50}\n🔁 ROUND {round_n} @ "
              f"{datetime.now().strftime('%H:%M:%S')}\n{'='*50}", flush=True)
        for i in range(start_idx, len(pids)):
            pid = pids[i]
            tag = pid[:8]
            try:
                st = run_visit(pid, tag, args.session.strip().removeprefix("session-"),
                               args.threads, args.dwell, env)
            except Exception as e:
                st = f"error: {str(e)[:100]}"
            results[tag] = st
            print(f"   [{tag}] round done: {st}", flush=True)
            ok = sum(1 for v in results.values() if v.startswith("ok"))
            print(f"   📊 round score: {ok}/{len(pids)} verified", flush=True)
            try:
                _json.dump({"round": round_n, "next_idx": (i + 1) % len(pids)},
                           open(progress_file, "w"))
            except Exception:
                pass
        round_n += 1


if __name__ == "__main__":
    main()
