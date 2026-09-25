#!/usr/bin/env python3
"""Railway SSH that never trusts empty output: one op per call + sentinel + retry.

`railway ssh` intermittently drops the command and returns rc=0 with no stdout.
Every call here verifies an expected sentinel and retries.
"""
from __future__ import annotations

import time

from cell_ops import load_map, linked_cwd, rw_env  # noqa

MAX_TRIES = 4


def ssh_checked(
    home,
    service: str,
    script: str,
    sentinel: str,
    *,
    timeout: int = 200,
    tries: int = MAX_TRIES,
) -> tuple[bool, str]:
    """Run one python heredoc on a cell. True only if sentinel came back."""
    import subprocess

    env = rw_env(home)
    cwd = linked_cwd(home, service)
    # ponytail: `railway ssh` drops the FIRST line of stdout (verified 2026-09-25:
    # `echo HI; hostname` -> only hostname; `hostname; echo HI` -> both).
    # Spend a throwaway line so the real output survives.
    script = "echo\n" + script
    last = ""
    for i in range(tries):
        r = subprocess.run(
            ["railway", "ssh", "-s", service, "--", "bash", "-lc", script],
            cwd=cwd, env=env, capture_output=True, timeout=timeout,
        )
        out = (r.stdout or b"").decode("utf-8", "replace")
        if sentinel in out:
            return True, out
        last = out.strip()[-300:] + " | " + (r.stderr or b"").decode("utf-8", "replace")[-200:]
        time.sleep(6)
    return False, last
