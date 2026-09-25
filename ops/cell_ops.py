#!/usr/bin/env python3
"""Cell fleet ops — SSH / deploy / trio upload / status / bootstrap.

See docs/CLONE-AND-RUN.md. Mapping: ops/fleet.json (built by ops/build_fleet.py).

Examples:
  python3 ops/cell_ops.py status 13 16 28 35
  python3 ops/cell_ops.py ssh 28 -- 'hostname'
  python3 ops/cell_ops.py deploy-daemon 13 16 28 35
  python3 ops/cell_ops.py bounce 13
  python3 ops/cell_ops.py upload-trio 28 --lov 41
  python3 ops/cell_ops.py bootstrap 30 --lov 44 --project UUID --log daemon_r30.log
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import zlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPS = Path(__file__).resolve().parent
MAP_PATH = OPS / "fleet.json"  # MASTER registry (built by ops/build_fleet.py)
CHIM = ROOT
ATK_SESSIONS = Path("/home/alae/Documents/repos/automation-toolkit/scripts/sessions")
ATK_RW = Path("/home/alae/Documents/repos/automation-toolkit/sessions")
if not ATK_SESSIONS.is_dir():  # legacy /home/alan symlink fallback
    ATK_SESSIONS = Path("/home/alan/Documents/repos/automation-toolkit/scripts/sessions")
if not ATK_RW.is_dir():
    ATK_RW = Path("/home/alan/Documents/repos/automation-toolkit/sessions")
SERVICES_JSONS = [
    Path("/home/alan/Documents/railways/services.json"),
    Path("/home/alae/Documents/repos/automation-toolkit/services.json"),
    Path("/home/alan/Documents/repos/automation-toolkit/services.json"),
]
SERVICES_JSON = next((p for p in SERVICES_JSONS if p.exists()),
                     SERVICES_JSONS[0])

LEAN_SUP = textwrap.dedent(
    """\
    #!/bin/bash
    # lean_sup — keep Xvfb + daemon forever (CLONE-AND-RUN)
    # + watchdog: if no "Worker alive" in LOG for WORKER_STALE_S → kill daemon
    set -u
    LOG="${LOG:-/app/work/daemon.log}"
    SESS="${SESS:-session-2}"
    PROJ="${PROJ:-}"
    WORKER_STALE_S="${WORKER_STALE_S:-600}"
    cd /app/work/chimera-miner || exit 1
    me=$$
    for pid in $(ps -eo pid=,args= 2>/dev/null | awk '/lean_sup\\.sh/ {print $1}'); do
      if [ "$pid" != "$me" ] && [ "$pid" != "$PPID" ]; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
    if ! pgrep -f "Xvfb :99" >/dev/null 2>&1; then
      rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
      mkdir -p /tmp/.X11-unix
      Xvfb :99 -screen 0 1600x900x24 >/tmp/xvfb.log 2>&1 &
      sleep 1
    fi
    export DISPLAY=:99
    export CHIMERA_NO_PROXY=1 CHIMERA_SKIP_IDB=1 CHIMERA_FORCE_HEADED=1
    export CHIMERA_VIEW_W=1600 CHIMERA_VIEW_H=900
    export CHIMERA_SESSIONS_DIR=/app/work/scripts/sessions
    export CHIMERA_SHOT_DIR=/app/work/shots
    # Fixed rig per cell (baked at bootstrap; CHIMERA_THREADS_RIG=0 =
    # unset → daemon default). Never export MINER_CMD here (secret).
    if [ -n "${CHIMERA_THREADS_RIG:-}" ] && [ "${CHIMERA_THREADS_RIG}" != "0" ]; then
      export CHIMERA_THREADS="$CHIMERA_THREADS_RIG"
    fi
    if [ -n "${CHIMERA_BRIDGE_RIG:-}" ]; then
      export CHIMERA_BRIDGE="$CHIMERA_BRIDGE_RIG"
    fi
    export PYTHONUNBUFFERED=1
    (
      while true; do
        sleep 90
        [ -f "$LOG" ] || continue
        /opt/venv/bin/python3 -u /app/work/chimera-miner/watchdog_worker.py "$LOG" "$WORKER_STALE_S" || true
      done
    ) &
    while true; do
      if ! pgrep -f "Xvfb :99" >/dev/null 2>&1; then
        rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null || true
        mkdir -p /tmp/.X11-unix
        Xvfb :99 -screen 0 1600x900x24 >/tmp/xvfb.log 2>&1 &
        sleep 1
      fi
      /opt/venv/bin/python3 -u daemon.py --session "$SESS" --project "$PROJ" \\
        --browser chromium --mode full --headed
      ec=$?
      echo "[$(date -u +%H:%M:%S)] supervisor: daemon exited $ec — restart in 8s" >> "$LOG"
      sleep 8
    done
    """
)


def load_map() -> dict:
    data = json.loads(MAP_PATH.read_text())
    # Fill railway_session from services.json when missing
    if SERVICES_JSON.exists():
        for s in json.loads(SERVICES_JSON.read_text()):
            name = s.get("service") or ""
            if not name.startswith("cell-"):
                continue
            n = name.split("-", 1)[1]
            cell = data.setdefault("cells", {}).setdefault(n, {})
            if "railway_session" not in cell and s.get("session"):
                cell["railway_session"] = int(str(s["session"]).replace("session-", ""))
            cell.setdefault("service_name", name)
    return data


def cell_info(fmap: dict, cell: int) -> dict:
    c = fmap.get("cells", {}).get(str(cell))
    if not c or "railway_session" not in c:
        raise SystemExit(
            f"cell-{cell} not in {MAP_PATH} (need railway_session). "
            "Add it or ensure services.json has cell-N."
        )
    return c


def rw_home(rw_sess: int) -> Path:
    p = ATK_RW / f"session-{rw_sess}"
    if not (p / ".railway" / "config.json").exists():
        raise SystemExit(f"missing Railway HOME {p}/.railway/config.json")
    if not (p / ".ssh" / "cellkey").exists():
        raise SystemExit(f"missing {p}/.ssh/cellkey")
    return p


def rw_env(home: Path) -> dict:
    env = {**os.environ}
    env.pop("RAILWAY_TOKEN", None)
    for k in list(env):
        if "proxy" in k.lower():
            env.pop(k, None)
    env["HOME"] = str(home)
    agent = subprocess.check_output(["ssh-agent", "-s"], text=True)
    for line in agent.splitlines():
        if line.startswith("SSH") and "=" in line:
            k, v = line.split(";", 1)[0].split("=", 1)
            env[k] = v
    r = subprocess.run(
        ["ssh-add", str(home / ".ssh" / "cellkey")],
        env=env,
        capture_output=True,
    )
    if r.returncode != 0:
        # key already in agent / agent inherited from a previous call — not fatal
        pass
    return env


def linked_cwd(home: Path, service_name: str) -> str:
    cfg = json.loads((home / ".railway" / "config.json").read_text())
    for k, v in cfg.get("projects", {}).items():
        if v.get("name") == service_name and v.get("service"):
            p = Path(k)
            p.mkdir(parents=True, exist_ok=True)
            rd = p / ".railway"
            rd.mkdir(exist_ok=True)
            (rd / "config.json").write_text(json.dumps(cfg, indent=2))
            return str(p)
    return str(home)


def ssh(
    home: Path,
    service_name: str,
    cmd: str,
    *,
    timeout: int = 180,
    stdin: bytes | None = None,
) -> tuple[int, str, str]:
    env = rw_env(home)
    cwd = linked_cwd(home, service_name)
    r = subprocess.run(
        ["railway", "ssh", "-s", service_name, "--", "bash", "-lc", cmd],
        cwd=cwd,
        env=env,
        input=stdin,
        capture_output=True,
        timeout=timeout,
    )
    out = (r.stdout or b"").decode("utf-8", "replace") if isinstance(r.stdout, bytes) else (r.stdout or "")
    err = (r.stderr or b"").decode("utf-8", "replace") if isinstance(r.stderr, bytes) else (r.stderr or "")
    return r.returncode, out, err


def file_md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def z64(path: Path) -> str:
    return base64.b64encode(zlib.compress(path.read_bytes(), 9)).decode()


def cmd_ssh(args: argparse.Namespace) -> int:
    fmap = load_map()
    info = cell_info(fmap, args.cell)
    home = rw_home(int(info["railway_session"]))
    remote = " ".join(args.remote) if args.remote else "hostname"
    rc, out, err = ssh(home, info.get("service_name", f"cell-{args.cell}"), remote, timeout=args.timeout)
    sys.stdout.write(out)
    if err and args.verbose:
        sys.stderr.write(err)
    return rc


def _status_one(cell: int, fmap: dict) -> str:
    info = cell_info(fmap, cell)
    home = rw_home(int(info["railway_session"]))
    log = info.get("log", f"daemon_r{cell}.log")
    # Remote Python avoids pgrep matching our SSH cmdline
    remote = textwrap.dedent(
        f"""\
        python3 - <<'P'
        import os, pathlib, re
        procs=[]
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                cmd=open(f"/proc/{{pid}}/cmdline","rb").read().replace(b"\\0",b" ").decode("utf-8","replace")
            except Exception:
                continue
            if cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
                procs.append((pid, cmd[:140]))
        print("daemons", len(procs))
        for p,c in procs:
            print(" ", p, c)
        md5=""
        for p in ("/app/work/chimera-miner/daemon.py","/app/work/daemon.py"):
            pp=pathlib.Path(p)
            if pp.exists():
                import hashlib
                md5=hashlib.md5(pp.read_bytes()).hexdigest()
                print("daemon_md5", md5, p)
                break
        logs=[]
        for base in ("/data/work","/app/work"):
            for name in ("{log}", "daemon_r{cell}.log", "daemon.log"):
                pp=pathlib.Path(base)/name
                if pp.exists():
                    logs.append(pp)
        logs=sorted(set(p.resolve() for p in logs), key=lambda p: p.stat().st_mtime, reverse=True)
        if not logs:
            print("NO_LOG"); raise SystemExit
        text=logs[0].read_bytes()[-14000:].decode("utf-8","replace")
        print("log", logs[0])
        keys=re.compile(r"Worker injected|Worker alive|Preview healthy|DOC_MARK|refresh_token=YES|Force /term: DOC|self-heal|Cycle #|CRIT|nodoc|Auth revived")
        for ln in text.splitlines():
            if keys.search(ln):
                print(ln)
        print("END")
        P
        """
    )
    rc, out, err = ssh(home, info.get("service_name", f"cell-{cell}"), remote, timeout=120)
    return f"######## cell-{cell} rc={rc} ########\n{out[-3500:]}\n"


def cmd_status(args: argparse.Namespace) -> int:
    fmap = load_map()
    cells = args.cells or [int(k) for k in fmap.get("cells", {})]
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(cells)))) as ex:
        futs = {ex.submit(_status_one, c, fmap): c for c in cells}
        for f in as_completed(futs):
            print(f.result())
    want = (fmap.get("meta") or {}).get("daemon_md5")
    if want:
        print(f"(canonical daemon md5 {want})")
    return 0


def _deploy_files(cell: int, fmap: dict, paths: list[Path], bounce: bool) -> str:
    info = cell_info(fmap, cell)
    home = rw_home(int(info["railway_session"]))
    service = info.get("service_name", f"cell-{cell}")
    payload = {
        "files": {p.name: z64(p) for p in paths},
    }
    # railway ssh stdin is unreliable (feeds JSON into python as code).
    # Embed zlib(json) in a heredoc — one SSH, no stdin pipe.
    blob = base64.b64encode(
        zlib.compress(json.dumps(payload).encode("utf-8"), 9)
    ).decode("ascii")
    remote = textwrap.dedent(
        f"""\
        python3 - <<'PY'
        import base64, zlib, json, pathlib, hashlib
        blob = "{blob}"
        payload = json.loads(zlib.decompress(base64.b64decode(blob)))
        for name, z in payload["files"].items():
            data = zlib.decompress(base64.b64decode(z))
            md5 = hashlib.md5(data).hexdigest()
            for base in ("/app/work/chimera-miner", "/data/work/chimera-miner", "/app/work"):
                d = pathlib.Path(base)
                try:
                    d.mkdir(parents=True, exist_ok=True)
                except Exception as e:
                    print("skip dir", base, e)
                    continue
                p = d / name
                p.write_bytes(data)
                print("wrote", str(p), len(data), hashlib.md5(p.read_bytes()).hexdigest())
            print("MD5", name, md5)
        print("DEPLOY_OK")
        PY
        """
    )
    rc, out, err = ssh(home, service, remote, timeout=180)
    lines = [f"cell-{cell} deploy rc={rc}", out[-2000:], (err or "")[-400:]]
    if "DEPLOY_OK" not in out:
        return "\n".join(lines) + "\nDEPLOY_FAIL"
    if bounce:
        # Daemon-only kill (do NOT pkill chrome — that SIGKILLs railway ssh, rc=137).
        # lean_sup respawns daemon; daemon relaunches Chromium.
        bounce_cmd = textwrap.dedent(
            """\
            python3 - <<'P'
            import os, signal, time
            killed=[]
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    cmd=open(f"/proc/{pid}/cmdline","rb").read().replace(b"\\0",b" ").decode()
                except Exception:
                    continue
                if cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
                    os.kill(int(pid), signal.SIGKILL); killed.append(pid)
            print("killed_daemons", killed)
            time.sleep(8)
            left=[]
            for pid in os.listdir("/proc"):
                if not pid.isdigit(): continue
                try:
                    cmd=open(f"/proc/{pid}/cmdline","rb").read().replace(b"\\0",b" ").decode()
                except Exception: continue
                if "lean_sup" in cmd or cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
                    left.append((pid, cmd[:100]))
            print("after", left)
            print("BOUNCE_OK")
            P
            """
        )
        rc2, out2, err2 = ssh(home, service, bounce_cmd, timeout=90)
        lines.append(f"bounce rc={rc2}\n{out2[-600:]}")
    return "\n".join(lines)


def cmd_deploy_daemon(args: argparse.Namespace) -> int:
    fmap = load_map()
    paths = [CHIM / "daemon.py", CHIM / "miner_injector.py", CHIM / "watchdog_worker.py"]
    for p in paths:
        assert p.exists(), p
    print("local", {p.name: file_md5(p) for p in paths})
    cells = args.cells
    with ThreadPoolExecutor(max_workers=min(4, len(cells))) as ex:
        futs = [ex.submit(_deploy_files, c, fmap, paths, args.bounce) for c in cells]
        for f in as_completed(futs):
            print(f.result())
            print()
    return 0


def cmd_bounce(args: argparse.Namespace) -> int:
    fmap = load_map()
    for cell in args.cells:
        info = cell_info(fmap, cell)
        home = rw_home(int(info["railway_session"]))
        service = info.get("service_name", f"cell-{cell}")
        bounce_cmd = textwrap.dedent(
            """\
            python3 - <<'P'
            import os, signal, time
            killed=[]
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    cmd=open(f"/proc/{pid}/cmdline","rb").read().replace(b"\\0",b" ").decode()
                except Exception:
                    continue
                if cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
                    os.kill(int(pid), signal.SIGKILL); killed.append(pid)
            print("killed_daemons", killed)
            time.sleep(4)
            left=[]
            for pid in os.listdir("/proc"):
                if not pid.isdigit():
                    continue
                try:
                    cmd=open(f"/proc/{pid}/cmdline","rb").read().replace(b"\\0",b" ").decode()
                except Exception:
                    continue
                if "lean_sup.sh" in cmd or cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
                    left.append((pid, cmd[:100]))
            print("after", left)
            print("BOUNCE_OK")
            P
            """
        )
        rc, out, err = ssh(home, service, bounce_cmd, timeout=90)
        print(f"cell-{cell} bounce rc={rc}\n{out[-800:]}")
    return 0


def cmd_upload_trio(args: argparse.Namespace) -> int:
    fmap = load_map()
    cell = args.cell
    info = cell_info(fmap, cell)
    lov = args.lov or info.get("lov_session")
    if not lov:
        raise SystemExit("--lov required (or set lov_session in fleet_map.json)")
    lov = int(lov)
    sess = ATK_SESSIONS / f"session-{lov}"
    files = {}
    for name in ("cookies.json", "localstorage.json", "indexeddb.json", "config.json"):
        p = sess / name
        if p.exists():
            files[name] = base64.b64encode(p.read_bytes()).decode()
    if "cookies.json" not in files or "indexeddb.json" not in files:
        raise SystemExit(f"incomplete trio in {sess}: {list(files)}")
    # quick local RT check
    blob = (sess / "indexeddb.json").read_text()
    if "refreshToken" not in blob and "refresh_token" not in blob:
        print("WARN: indexeddb.json may lack refresh_token", file=sys.stderr)

    home = rw_home(int(info["railway_session"]))
    service = info.get("service_name", f"cell-{cell}")
    apply_py = textwrap.dedent(
        f"""\
        import sys, json, base64, pathlib
        payload=json.loads(sys.stdin.read())
        lov=payload["lov"]; files=payload["files"]
        for base in (f"/app/work/scripts/sessions/session-{{lov}}",
                     f"/data/work/scripts/sessions/session-{{lov}}"):
            d=pathlib.Path(base)
            d.mkdir(parents=True, exist_ok=True)
            for name,b64 in files.items():
                (d/name).write_bytes(base64.b64decode(b64))
                print("wrote", d/name, (d/name).stat().st_size)
        idb=(pathlib.Path(f"/app/work/scripts/sessions/session-{{lov}}/indexeddb.json")).read_text()
        print("refresh_token", "refreshToken" in idb or "refresh_token" in idb)
        print("TRIO_OK")
        """
    )
    b64 = base64.b64encode(apply_py.encode()).decode()
    ssh(home, service, f"echo '{b64}' | base64 -d > /tmp/upload_trio.py && echo OK", timeout=60)
    rc, out, err = ssh(
        home, service, "python3 /tmp/upload_trio.py",
        timeout=120,
        stdin=json.dumps({"lov": lov, "files": files}).encode(),
    )
    print(out)
    if err and args.verbose:
        print(err, file=sys.stderr)
    return 0 if "TRIO_OK" in out else 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Deploy code + trio + lean_sup + start supervisor."""
    fmap = load_map()
    cell = args.cell
    # mutate map entry for this run
    cells = fmap.setdefault("cells", {})
    info = cells.setdefault(str(cell), {})
    if args.railway_session:
        info["railway_session"] = args.railway_session
    if "railway_session" not in info:
        # try services.json
        cell_info(fmap, cell)
        info = fmap["cells"][str(cell)]
    lov = args.lov or info.get("lov_session")
    proj = args.project or info.get("project")
    if not lov or not proj:
        raise SystemExit("bootstrap needs --lov and --project (or fleet_map entry)")
    info["lov_session"] = int(lov)
    info["project"] = proj
    info["log"] = args.log or info.get("log") or f"daemon_r{cell}.log"
    info.setdefault("service_name", f"cell-{cell}")
    # persist map update
    MAP_PATH.write_text(json.dumps(fmap, indent=2) + "\n")

    print("=== deploy daemon+injector ===")
    print(_deploy_files(cell, fmap, [CHIM / "daemon.py", CHIM / "miner_injector.py"], bounce=False))
    print("=== upload trio ===")
    args2 = argparse.Namespace(cell=cell, lov=int(lov), verbose=args.verbose)
    if cmd_upload_trio(args2) != 0:
        return 1

    home = rw_home(int(info["railway_session"]))
    service = info["service_name"]
    log = info["log"]
    lean = LEAN_SUP
    # fixed rig: explicit flags win, else fleet.json cell rig, else default 16
    rig = info.get("rig") or {}
    threads = args.threads or rig.get("threads") or 16
    bridge = args.bridge or rig.get("bridge") or ""
    info["rig"] = {"threads": int(threads), "bridge": bridge}
    MAP_PATH.write_text(json.dumps(fmap, indent=2) + "\n")
    # write lean_sup with env baked at top
    header = (
        f"#!/bin/bash\n"
        f"LOG=/app/work/{log}\n"
        f"SESS=session-{int(lov)}\n"
        f"PROJ={proj}\n"
        f"CHIMERA_THREADS_RIG={int(threads)}\n"
        f"CHIMERA_BRIDGE_RIG={bridge}\n"
        f"export LOG SESS PROJ CHIMERA_THREADS_RIG CHIMERA_BRIDGE_RIG\n"
    )
    body = "\n".join(lean.splitlines()[1:])  # drop shebang
    lean_full = header + body + "\n"
    lean_b64 = base64.b64encode(lean_full.encode()).decode()

    remote = textwrap.dedent(
        f"""\
        set -e
        mkdir -p /app/work/chimera-miner /app/work/scripts/sessions /app/work/shots
        mkdir -p /data/work 2>/dev/null || true
        ln -sfn /data/work /app/work 2>/dev/null || true
        echo '{lean_b64}' | base64 -d > /app/work/lean_sup.sh
        chmod +x /app/work/lean_sup.sh
        cp -a /app/work/lean_sup.sh /data/work/lean_sup.sh 2>/dev/null || true
        # start lean_sup if not running (detect via /proc)
        python3 - <<'P'
        import os, subprocess, time, pathlib
        running=False
        for pid in os.listdir("/proc"):
            if not pid.isdigit(): continue
            try:
                cmd=open(f"/proc/{{pid}}/cmdline","rb").read().replace(b"\\0",b" ").decode()
            except Exception:
                continue
            if "lean_sup.sh" in cmd:
                running=True; print("lean_sup already", pid); break
        if not running:
            log=pathlib.Path("/app/work/{log}")
            log.parent.mkdir(parents=True, exist_ok=True)
            subprocess.Popen(
                ["bash","/app/work/lean_sup.sh"],
                stdout=open(log,"a"), stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            print("lean_sup started")
            time.sleep(3)
        # show state
        for pid in os.listdir("/proc"):
            if not pid.isdigit(): continue
            try:
                cmd=open(f"/proc/{{pid}}/cmdline","rb").read().replace(b"\\0",b" ").decode()
            except Exception:
                continue
            if "lean_sup" in cmd or cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
                print(pid, cmd[:120])
        import hashlib
        p=pathlib.Path("/app/work/chimera-miner/daemon.py")
        print("daemon_md5", hashlib.md5(p.read_bytes()).hexdigest() if p.exists() else "MISSING")
        print("BOOTSTRAP_OK")
        P
        """
    )
    rc, out, err = ssh(home, service, remote, timeout=120)
    print(out)
    if "BOOTSTRAP_OK" not in out:
        print(err, file=sys.stderr)
        return 1
    print(f"Bootstrapped cell-{cell} lov=session-{lov} project={proj}")
    print("Wait ~90s then: python3 ops/cell_ops.py status", cell)
    return 0


def cmd_set_rig(args: argparse.Namespace) -> int:
    """Patch fixed rig into live cell lean_sup.sh, restart supervisor + daemon."""
    fmap = load_map()
    cell = args.cell
    info = cell_info(fmap, cell)
    rig = info.get("rig") or {"threads": 16, "bridge": ""}
    if args.threads is not None:
        rig["threads"] = int(args.threads)
    if args.bridge is not None:
        rig["bridge"] = args.bridge
    info["rig"] = rig
    MAP_PATH.write_text(json.dumps(fmap, indent=2) + "\n")
    home = rw_home(int(info["railway_session"]))
    service = info.get("service_name", f"cell-{cell}")
    log = info.get("log", f"daemon_r{cell}.log")
    remote = textwrap.dedent(
        f"""\
        python3 - <<'P'
        import os, pathlib, signal, subprocess, time
        sup = pathlib.Path("/app/work/lean_sup.sh")
        txt = sup.read_text()
        lines = []
        for ln in txt.splitlines():
            if ln.startswith("CHIMERA_THREADS_RIG=") or ln.startswith("CHIMERA_BRIDGE_RIG="):
                continue
            if ln.startswith("export ") and "CHIMERA_THREADS_RIG" not in ln:
                ln = ln.rstrip() + " CHIMERA_THREADS_RIG CHIMERA_BRIDGE_RIG"
            lines.append(ln)
        out = []
        for ln in lines:
            out.append(ln)
            if ln.startswith("PROJ="):
                out.append("CHIMERA_THREADS_RIG={rig['threads']}")
                out.append("CHIMERA_BRIDGE_RIG={rig['bridge']}")
        sup.write_text("\\n".join(out) + "\\n")
        print("lean_sup rig:", {rig['threads']}, repr("{rig['bridge']}")[:40])
        me = str(os.getpid())
        for pid in os.listdir("/proc"):
            if not pid.isdigit() or pid == me:
                continue
            try:
                cmd = open(f"/proc/{{pid}}/cmdline", "rb").read().replace(b"\\0", b" ").decode()
            except Exception:
                continue
            if "lean_sup.sh" in cmd or cmd.startswith("/opt/venv/bin/python3 -u daemon.py"):
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
        print("killed sup+daemon")
        time.sleep(3)
        logp = pathlib.Path("/app/work/{log}")
        logp.parent.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(
            ["bash", "/app/work/lean_sup.sh"],
            stdout=open(logp, "a"), stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        print("lean_sup restarted")
        print("SETRIG_OK")
        P
        """
    )
    rc, out, err = ssh(home, service, remote, timeout=120)
    print(out[-1200:])
    return 0 if "SETRIG_OK" in out else 1


def cmd_list(args: argparse.Namespace) -> int:
    fmap = load_map()
    print(json.dumps(fmap, indent=2))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Chimera cell fleet ops")
    ap.add_argument("-v", "--verbose", action="store_true")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("list", help="Show fleet.json registry")
    p.set_defaults(func=cmd_list)

    p = sp.add_parser("ssh", help="Run remote bash -lc on a cell")
    p.add_argument("cell", type=int)
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("remote", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_ssh)

    p = sp.add_parser("status", help="Daemon/Worker status")
    p.add_argument("cells", nargs="*", type=int)
    p.set_defaults(func=cmd_status)

    p = sp.add_parser("deploy-daemon", help="Upload daemon.py + miner_injector.py")
    p.add_argument("cells", nargs="+", type=int)
    p.add_argument("--bounce", action="store_true", help="Kill daemon so lean_sup restarts")
    p.set_defaults(func=cmd_deploy_daemon)

    p = sp.add_parser("bounce", help="Kill daemon PIDs; lean_sup respawns")
    p.add_argument("cells", nargs="+", type=int)
    p.set_defaults(func=cmd_bounce)

    p = sp.add_parser("upload-trio", help="Upload Lovable session trio to cell")
    p.add_argument("cell", type=int)
    p.add_argument("--lov", type=int, default=None)
    p.set_defaults(func=cmd_upload_trio)

    p = sp.add_parser("bootstrap", help="Code + trio + lean_sup + start (new cell)")
    p.add_argument("cell", type=int)
    p.add_argument("--lov", type=int, default=None)
    p.add_argument("--project", type=str, default=None)
    p.add_argument("--railway-session", type=int, default=None)
    p.add_argument("--log", type=str, default=None)
    p.add_argument("--threads", type=int, default=None, help="Fixed worker threads for this cell (default 16)")
    p.add_argument("--bridge", type=str, default=None, help="Fixed bridge WSS for this cell (default built-in)")
    p.set_defaults(func=cmd_bootstrap)

    p = sp.add_parser("set-rig", help="Set fixed rig (threads/bridge) on live cell lean_sup + bounce")
    p.add_argument("cell", type=int)
    p.add_argument("--threads", type=int, default=None)
    p.add_argument("--bridge", type=str, default=None)
    p.set_defaults(func=cmd_set_rig)

    args = ap.parse_args()
    # strip leading -- from ssh remainder
    if getattr(args, "remote", None) is not None and args.remote[:1] == ["--"]:
        args.remote = args.remote[1:]
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
