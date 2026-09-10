#!/usr/bin/env python3
"""DB backends for script3_launch_miner.

Modes (select with --db):
  local   (default) — farm system on disk, NO Mega, NO git push.
                      Sessions: <sessions-dir>/session-N/{config.json,cookies.json}
                      Projects: session config project_id/project_link + finals/lovables.json
  mega              — legacy chimera Mega DB (mega:chimera/database.json via rclone).
  github            — local farm reads/writes PLUS git commit+push of the repo
                      (sessions + script3_db.json state) after every status change.
                      GH token is NEVER committed: resolved at runtime from
                      GH_TOKEN/GITHUB_TOKEN env, else from an encrypted file
                      (~/.config/chimera/gh_token.enc) decrypted with the
                      Fernet key in CHIMERA_GH_KEY env.

Helper:
  python3 db_backend.py encrypt-token [--out PATH]
      Reads token from GH_TOKEN env (or getpass prompt) and writes the
      Fernet-encrypted file. Generate a key with:
          python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import base64
import getpass
import json
import os
import subprocess
import sys
from pathlib import Path

FARM_SESSIONS_DIR = "/home/alan/Documents/repos/automation-toolkit/scripts/sessions"
FARM_FINALS_DIR = "/home/alan/Documents/repos/automation-toolkit/finals"
REPO_DIR = "/home/alan/Documents/repos/automation-toolkit"
STATE_FILENAME = "script3_db.json"
GH_TOKEN_FILE = str(Path.home() / ".config" / "chimera" / "gh_token.enc")


# --------------------------------------------------------------------------
# GH token handling (encrypted at rest, decrypted only at runtime)
# --------------------------------------------------------------------------
def _resolve_gh_token(token_file: str | None = None) -> str | None:
    """Return a GH token or None. Never prints/logs the value."""
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if tok:
        return tok.strip()
    enc_path = Path(token_file or GH_TOKEN_FILE)
    if not enc_path.exists():
        return None
    key = os.environ.get("CHIMERA_GH_KEY", "").strip()
    if not key:
        print("⚠️  Encrypted GH token exists but CHIMERA_GH_KEY env is unset", file=sys.stderr)
        return None
    try:
        from cryptography.fernet import Fernet
        return Fernet(key.encode()).decrypt(enc_path.read_bytes()).decode().strip()
    except Exception as e:
        print(f"⚠️  GH token decrypt failed: {e}", file=sys.stderr)
        return None


def encrypt_token_cmd(out: str | None = None) -> int:
    tok = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or getpass.getpass("GH token: ")
    tok = tok.strip()
    if not tok:
        print("❌ empty token", file=sys.stderr)
        return 1
    key = os.environ.get("CHIMERA_GH_KEY", "").strip()
    if not key:
        print("❌ CHIMERA_GH_KEY env is required (Fernet key)", file=sys.stderr)
        return 1
    try:
        from cryptography.fernet import Fernet
        out_path = Path(out or GH_TOKEN_FILE)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(Fernet(key.encode()).encrypt(tok.encode()))
        os.chmod(out_path, 0o600)
        print(f"✅ Encrypted token written to {out_path} (mode 0600, safe to keep out of git)")
        return 0
    except Exception as e:
        print(f"❌ encrypt failed: {e}", file=sys.stderr)
        return 1


def _git(repo: str, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True, text=True, timeout=120,
    )


# --------------------------------------------------------------------------
# Local farm backend (disk only)
# --------------------------------------------------------------------------
def _read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _iter_session_configs(sessions_dir: Path):
    for child in sorted(sessions_dir.glob("session-*")):
        if not child.is_dir():
            continue
        cfg = _read_json(child / "config.json")
        if isinstance(cfg, dict):
            yield child.name, cfg


class LocalBackend:
    """Farm system on local disk. Identity comes from session config.json."""

    name = "local"

    def __init__(self, sessions_dir: str | None = None, finals_dir: str | None = None):
        self.sessions_dir = Path(sessions_dir or os.environ.get("CHIMERA_SESSIONS_DIR", FARM_SESSIONS_DIR))
        self.finals_dir = Path(finals_dir or FARM_FINALS_DIR)

    # -- sessions ------------------------------------------------------
    def _config_path(self, session_id: str) -> Path:
        sid = session_id if session_id.startswith("session-") else f"session-{session_id}"
        return self.sessions_dir / sid / "config.json"

    def get_session(self, session_id: str) -> dict | None:
        cfg = _read_json(self._config_path(session_id))
        if not isinstance(cfg, dict):
            return None
        sid = session_id if session_id.startswith("session-") else f"session-{session_id}"
        return {
            "id": sid,
            "email": cfg.get("email", "unknown"),
            "status": cfg.get("status", "active"),
            "config": cfg,
        }

    def update_session(self, session_id: str, **fields) -> None:
        path = self._config_path(session_id)
        cfg = _read_json(path) or {}
        cfg.update(fields)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2))
        self.persist([str(path)])

    def mark_session_red(self, session_id: str) -> None:
        self.update_session(session_id, status="red")

    def add_session(self, session_id: str, email: str, status: str = "active") -> dict:
        path = self._config_path(session_id)
        if not path.exists():
            cfg = {"email": email, "password": email, "status": status, "verified": False}
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(cfg, indent=2))
            self.persist([str(path)])
        return self.get_session(session_id)

    # -- projects ------------------------------------------------------
    @staticmethod
    def _record_for(pid: str, created_by: str | None, invite_link=None, chat_url=None,
                    preview_url=None, usage_count: int = 0) -> dict:
        return {
            "project_id": pid,
            "chat_url": chat_url or f"https://lovable.dev/projects/{pid}",
            "preview_url": preview_url or f"https://{pid}.lovableproject.com",
            "invite_link": invite_link,
            "created_by": created_by,
            "usage_count": usage_count,
            "max_usage": 20,
            "status": "ready",
        }

    def _finals_records(self):
        for fn in ("lovables.json", "all_lovables_final.json"):
            data = _read_json(self.finals_dir / fn)
            if isinstance(data, list):
                yield from (e for e in data if isinstance(e, dict))

    def get_project(self, project_id: str) -> dict | None:
        pid = project_id.strip().rstrip("/")
        if "/projects/" in pid:
            pid = pid.split("/projects/")[-1].split("?")[0].strip()
        # 1) session configs (canonical: project_id/project_link)
        for sid, cfg in _iter_session_configs(self.sessions_dir):
            if cfg.get("project_id") == pid or (cfg.get("project_link") or "").rstrip("/").endswith(pid):
                return self._record_for(
                    pid, f"session-{sid.split('session-')[-1]}" if not sid.startswith("session-") else sid,
                    chat_url=cfg.get("project_link"),
                    usage_count=0,
                )
        # 2) farm record files
        for e in self._finals_records():
            blob = json.dumps(e)
            if pid in blob:
                projs = e.get("projects")
                if isinstance(projs, list):
                    for p in projs:
                        if isinstance(p, dict) and (p.get("project_id") == pid or pid in json.dumps(p)):
                            p.setdefault("created_by", None)
                            p.setdefault("usage_count", 0)
                            p.setdefault("max_usage", 20)
                            return p
                mail = e.get("mail")
                owner = None
                if mail:
                    for sid, cfg in _iter_session_configs(self.sessions_dir):
                        if cfg.get("email") == mail:
                            owner = sid if sid.startswith("session-") else f"session-{sid}"
                            break
                return self._record_for(pid, owner)
        return None

    def get_account_linked_project(self, session_id: str) -> dict | None:
        cfg = _read_json(self._config_path(session_id))
        if not isinstance(cfg, dict):
            return None
        pid = (cfg.get("project_id") or "").strip()
        if not pid:
            return None
        sid = session_id if session_id.startswith("session-") else f"session-{session_id}"
        return self._record_for(
            pid, sid,
            chat_url=cfg.get("project_link"),
            usage_count=0,
        )

    def projects_for(self, session_id: str) -> list:
        out = []
        p = self.get_account_linked_project(session_id)
        if p:
            out.append(p)
        return out

    def set_project_linked(self, project_id: str, linked: bool) -> None:
        pass  # local mode: verification stamps are printed, not persisted

    # -- misc ----------------------------------------------------------
    def print_stats(self) -> None:
        from collections import Counter
        statuses, n_projects = Counter(), 0
        n_sessions = 0
        for _, cfg in _iter_session_configs(self.sessions_dir):
            n_sessions += 1
            statuses[cfg.get("status", "active")] += 1
            if (cfg.get("project_id") or "").strip():
                n_projects += 1
        print("=" * 60)
        print("📊 FARM DB STATS (local disk)")
        print("=" * 60)
        print(f"Sessions: {n_sessions} " + " ".join(f"{k}={v}" for k, v in sorted(statuses.items())))
        print(f"Projects linked in session configs: {n_projects}")
        print("=" * 60)

    def persist(self, paths: list | None = None) -> None:
        pass  # local: writes already hit disk in update_session


class MegaBackend:
    """Legacy chimera Mega DB (mega:chimera/database.json). Lazy import so
    local/github runs never touch Mega."""

    name = "mega"

    def print_stats(self):
        from mega_db import load_db
        load_db().print_stats()

    def get_session(self, session_id):
        from mega_db import load_db
        return load_db().get_session(session_id)

    def update_session(self, session_id, **fields):
        from mega_db import load_db, save_db, mega_distributed_lock
        with mega_distributed_lock(timeout=600):
            db = load_db()
            if db.get_session(session_id):
                db.update_session(session_id, **fields)
            save_db(db)

    def mark_session_red(self, session_id):
        from mega_db import load_db, save_db, mega_distributed_lock
        with mega_distributed_lock(timeout=600):
            db = load_db()
            db.mark_session_red(session_id)
            save_db(db)

    def add_session(self, session_id, email, status="active"):
        from mega_db import load_db, save_db, mega_distributed_lock
        with mega_distributed_lock(timeout=600):
            db = load_db()
            db.add_session(session_id, email, status)
            save_db(db)
            return db.get_session(session_id)

    def get_project(self, project_id):
        from mega_db import load_db
        return load_db().get_project(project_id)

    def get_account_linked_project(self, session_id):
        from mega_db import load_db
        return load_db().get_account_linked_project(session_id)

    def projects_for(self, session_id):
        from mega_db import load_db
        db = load_db()
        return [p for p in db.data.get("projects", []) if p.get("created_by") == session_id]

    def set_project_linked(self, project_id, linked):
        from mega_db import load_db, save_db, mega_distributed_lock
        with mega_distributed_lock(timeout=600):
            db = load_db()
            fresh = db.get_project(project_id)
            if fresh:
                fresh["linked"] = linked
            save_db(db)

    def persist(self, paths=None):
        pass  # mega writes happen inside each mutating call


class GithubBackend(LocalBackend):
    """Local farm reads/writes PLUS git commit+push of the repo state."""

    name = "github"

    def __init__(self, sessions_dir=None, finals_dir=None, repo=None, gh_token_file=None):
        super().__init__(sessions_dir, finals_dir)
        self.repo = repo or REPO_DIR
        self.gh_token_file = gh_token_file
        self._dirty: list[str] = []
        self._state_path = Path(self.repo) / STATE_FILENAME

    def _state(self) -> dict:
        data = _read_json(self._state_path)
        return data if isinstance(data, dict) else {"sessions": {}, "projects": {}}

    def _write_state(self, state: dict) -> None:
        self._state_path.write_text(json.dumps(state, indent=2))
        self._dirty.append(str(self._state_path))

    def update_session(self, session_id, **fields):
        super().update_session(session_id, **fields)
        sid = session_id if session_id.startswith("session-") else f"session-{session_id}"
        self._dirty.append(str(self._config_path(session_id)))
        try:
            state = self._state()
            st = state.setdefault("sessions", {}).setdefault(sid, {})
            st.update({k: v for k, v in fields.items() if k in ("status", "flag_reason")})
            self._write_state(state)
        except Exception as e:
            print(f"⚠️  State write failed: {e}", file=sys.stderr)

    def set_project_linked(self, project_id, linked):
        try:
            state = self._state()
            pr = state.setdefault("projects", {}).setdefault(project_id, {})
            pr["linked"] = linked
            self._write_state(state)
        except Exception as e:
            print(f"⚠️  State write failed: {e}", file=sys.stderr)

    def print_stats(self):
        super().print_stats()
        print(f"📦 github backend → repo: {self.repo} (state: {STATE_FILENAME})")

    def persist(self, paths=None):
        paths = list(dict.fromkeys((paths or []) + self._dirty))
        if not paths:
            return
        self._dirty = []
        repo = self.repo
        if _git(repo, "rev-parse", "--is-inside-work-tree").returncode != 0:
            print(f"⚠️  Not a git repo: {repo} — skipping push", file=sys.stderr)
            return
        # stage by absolute path (git -C handles it)
        add = _git(repo, "add", "--", *paths)
        if add.returncode != 0:
            print(f"⚠️  git add failed: {add.stderr[:200]}", file=sys.stderr)
            return
        if _git(repo, "diff", "--cached", "--quiet").returncode == 0:
            return  # nothing staged
        msg = "chore(script3): session/project state update"
        if _git(repo, "commit", "-m", msg, "--quiet").returncode != 0:
            print("⚠️  git commit failed", file=sys.stderr)
            return
        tok = _resolve_gh_token(self.gh_token_file)
        if not tok:
            print("⚠️  No GH token (GH_TOKEN env or encrypted file) — committed locally, push skipped",
                  file=sys.stderr)
            return
        branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        branch = branch.stdout.strip() or "main"
        # real header passed via argv (transient); never printed/logged
        push = subprocess.run(
            ["git", "-C", repo, "-c", f"http.extraHeader=Authorization: Bearer {tok}",
             "push", "origin", branch],
            capture_output=True, text=True, timeout=180,
        )
        if push.returncode != 0:
            print(f"⚠️  git push failed: {(push.stderr or '')[:200]}", file=sys.stderr)
        else:
            print(f"✅ Pushed script3 state to {branch}")


def build_backend(name: str, sessions_dir=None, finals_dir=None, repo=None,
                  gh_token_file=None):
    name = (name or "local").lower()
    if name == "mega":
        return MegaBackend()
    if name == "github":
        return GithubBackend(sessions_dir, finals_dir, repo, gh_token_file)
    return LocalBackend(sessions_dir, finals_dir)


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "encrypt-token":
        out = sys.argv[2] if len(sys.argv) > 2 else None
        raise SystemExit(encrypt_token_cmd(out))
    print(__doc__)
