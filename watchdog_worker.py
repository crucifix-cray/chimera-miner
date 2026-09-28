#!/usr/bin/env python3
"""Kill daemon.py if Worker alive/injected missing from log for too long.

Used by lean_sup.sh so cells never sit worker-dead forever.
Usage: watchdog_worker.py LOG_PATH STALE_SECONDS
"""
from __future__ import annotations

import calendar
import os
import re
import signal
import sys
import time


def kill_daemon(log: str, reason: str) -> None:
    try:
        with open(log, "a") as f:
            f.write(
                f"[{time.strftime('%H:%M:%S', time.gmtime())}] "
                f"watchdog: {reason}\n"
            )
    except Exception:
        pass
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode()
        except Exception:
            continue
        if cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
            try:
                os.kill(int(pid), signal.SIGKILL)
            except Exception:
                pass


def main() -> int:
    if len(sys.argv) < 3:
        return 2
    log, stale = sys.argv[1], int(sys.argv[2])
    try:
        age = time.time() - os.path.getmtime(log)
        if age < 180:
            return 0
        data = open(log, "rb").read()[-200_000:].decode("utf-8", "replace")
    except Exception:
        return 0

    hits: list[tuple[int, int, int]] = []
    for ln in data.splitlines():
        if "Worker alive" in ln or "Worker injected!" in ln:
            m = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\]", ln)
            if m:
                hits.append(tuple(map(int, m.groups())))  # type: ignore[arg-type]

    if not hits:
        # Still waiting for first Lovable sandbox / inject — do NOT kill.
        # Only bounce after we had a worker and then went silent.
        return 0

    # Grace period: a freshly (re)started daemon gets GRACE_S to boot its
    # browser and inject before any kill. Without this, the watchdog murders
    # every new daemon at the first 90s check and nothing can ever recover.
    GRACE_S = 900
    try:
        starts = [ln for ln in data.splitlines()
                  if "launch browser" in ln or "mine.sh" in ln and "restart in" in ln]
        if starts:
            m = re.match(r"\[(\d{2}):(\d{2}):(\d{2})\]", starts[-1])
            if m:
                hh, mm, ss = tuple(map(int, m.groups()))
                now2 = time.gmtime()
                start_ts = calendar.timegm(
                    (now2.tm_year, now2.tm_mon, now2.tm_mday, hh, mm, ss, 0, 0, 0)
                )
                if start_ts > time.time() + 60:
                    start_ts -= 86400
                if time.time() - start_ts < GRACE_S:
                    return 0
    except Exception:
        pass

    now = time.gmtime()
    hh, mm, ss = hits[-1]
    last_ts = calendar.timegm(
        (now.tm_year, now.tm_mon, now.tm_mday, hh, mm, ss, 0, 0, 0)
    )
    if last_ts > time.time() + 60:
        last_ts -= 86400
    gap = time.time() - last_ts
    if gap >= stale:
        kill_daemon(log, f"Worker stale {int(gap)}s (>{stale}s) — kill daemon")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
