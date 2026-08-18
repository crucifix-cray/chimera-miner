#!/usr/bin/env python3
"""
Mega Database Manager - Central state for Chimera
Uses rclone + Mega cloud storage as database
"""

import json
import os
import subprocess
import fcntl
import contextlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List

MEGA_REMOTE = "mega:chimera"
MEGA_DB_FILE = "database.json"
MEGA_LOCK_FILE = ".db_lock"
LOCAL_DB_PATH = Path("/tmp/chimera_database.json")
LOCK_FILE_PATH = Path("/tmp/chimera_database.lock")

PROXY_VARS = ["http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "no_proxy", "NO_PROXY"]


def _rclone_env():
    """Return environment without proxy vars (Tor proxy breaks rclone)."""
    return {k: v for k, v in os.environ.items() if k not in PROXY_VARS}


@contextlib.contextmanager
def db_lock():
    """
    Local file lock serializing read→modify→write on THIS machine.
    Blocks until the lock is free. Used by MegaDB.transaction().

    NOTE: flock only coordinates processes on the same host. For
    GitHub Actions (distributed runners), rely on claim-based session
    assignment so no two runners edit overlapping records.
    """
    lock_fd = open(LOCK_FILE_PATH, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


@contextlib.contextmanager
def mega_distributed_lock(timeout: int = 120, stale_after: int = 300):
    """
    Distributed lock stored ON MEGA so multiple machines (GitHub runners)
    can safely serialize read→modify→write of database.json.
    """
    import time
    import uuid

    timeout = int(os.environ.get("MEGA_LOCK_TIMEOUT", str(timeout)))
    stale_after = int(os.environ.get("MEGA_LOCK_STALE", str(stale_after)))

    token = uuid.uuid4().hex
    local_lock = Path("/tmp/chimera_remote_lock.json")
    remote_lock = f"{MEGA_REMOTE}/{MEGA_LOCK_FILE}"
    deadline = time.time() + timeout

    def _write_lock():
        with open(local_lock, "w") as f:
            json.dump({"token": token, "ts": time.time()}, f)

    def _read_lock():
        """Return (token, ts) from remote lock, or None."""
        tmp = Path("/tmp/chimera_remote_lock_check.json")
        r = subprocess.run(
            ["rclone", "copyto", remote_lock, str(tmp)],
            capture_output=True, text=True, timeout=60, env=_rclone_env()
        )
        if r.returncode == 0 and tmp.exists():
            try:
                with open(tmp) as f:
                    data = json.load(f)
                return data.get("token"), data.get("ts", 0)
            except Exception:
                return None
        return None

    def _delete_lock():
        subprocess.run(
            ["rclone", "delete", remote_lock],
            capture_output=True, text=True, timeout=60, env=_rclone_env()
        )

    acquired = False
    try:
        while time.time() < deadline:
            # 1. Write our lock file locally
            _write_lock()

            # 2. Upload (attempt to acquire)
            r = subprocess.run(
                ["rclone", "copyto", str(local_lock), remote_lock],
                capture_output=True, text=True, timeout=60, env=_rclone_env()
            )
            if r.returncode != 0:
                time.sleep(3)
                continue

            # 3. Verify ownership (re-read remote)
            time.sleep(2)  # let upload settle
            remote = _read_lock()
            if remote and remote[0] == token:
                acquired = True
                print("🔒 Distributed DB lock acquired", flush=True)
                break

            # 4. If remote lock is stale, steal it
            if remote and (time.time() - remote[1]) > stale_after:
                print("⚠️  Stealing stale distributed lock", flush=True)
                continue

            # 5. Lock held by someone else — wait and retry
            time.sleep(5)

        if not acquired:
            raise TimeoutError("Timed out waiting for distributed DB lock")

        yield
    finally:
        if acquired:
            _delete_lock()
            print("🔓 Distributed DB lock released", flush=True)


def unique_session_id() -> str:
    """Generate a globally-unique session ID (no collision across runners)."""
    import time
    return f"session-{int(time.time())}-{os.getpid()}"


class MegaDB:
    def __init__(self):
        self.data = {
            "sessions": [],
            "projects": [],
            "stats": {
                "total_sessions": 0,
                "active_sessions": 0,
                "on_hold_sessions": 0,
                "released_sessions": 0,
                "red_sessions": 0,
                "total_projects": 0,
                "ready_projects": 0,
                "in_use_projects": 0,
                "done_projects": 0,
                "active_miners": 0
            }
        }
        self.loaded = False
    
    @contextlib.contextmanager
    def transaction(self):
        """
        Atomic read→modify→write cycle protected by a local flock.
        
        Usage:
            with db.transaction() as db:
                db.add_project({...})
                db.update_session("session-1", status="on_hold")
        """
        with db_lock():
            self.sync_from_mega()
            yield self
            self.sync_to_mega()
    
    def sync_from_mega(self) -> bool:
        """Download database.json from Mega."""
        print("📥 Syncing database from Mega...")
        try:
            result = subprocess.run(
                ["rclone", "copyto", f"{MEGA_REMOTE}/{MEGA_DB_FILE}", str(LOCAL_DB_PATH)],
                capture_output=True,
                text=True,
                timeout=120,
                env=_rclone_env()
            )
            
            if result.returncode == 0 and LOCAL_DB_PATH.exists():
                with open(LOCAL_DB_PATH) as f:
                    self.data = json.load(f)
                # Normalize schema (ensure new fields exist for migrated DBs)
                self._ensure_schema()
                self._update_stats()
                self.loaded = True
                print(f"✅ Database loaded: {len(self.data['sessions'])} sessions, {len(self.data['projects'])} projects")
                return True
            else:
                print(f"⚠️  No database found on Mega, using empty database")
                if result.stderr.strip():
                    print(f"   rclone stderr: {result.stderr.strip()[:500]}")
                self.loaded = True
                return False
        except Exception as e:
            print(f"⚠️  Mega sync failed: {e}")
            self.loaded = True
            return False
    
    def sync_to_mega(self) -> bool:
        """Upload database.json to Mega."""
        print("📤 Syncing database to Mega...")
        try:
            # Update stats
            self._update_stats()
            
            # Save locally
            with open(LOCAL_DB_PATH, "w") as f:
                json.dump(self.data, f, indent=2)
            
            # Upload to Mega
            result = subprocess.run(
                ["rclone", "copyto", str(LOCAL_DB_PATH), f"{MEGA_REMOTE}/{MEGA_DB_FILE}"],
                capture_output=True,
                text=True,
                timeout=120,
                env=_rclone_env()
            )
            
            if result.returncode == 0:
                print("✅ Database synced to Mega")
                return True
            else:
                print(f"❌ Upload failed: {result.stderr}")
                return False
        except Exception as e:
            print(f"❌ Mega upload error: {e}")
            return False
    
    def _ensure_schema(self):
        """Normalize data structure for migrated DBs (add missing keys)."""
        # Ensure sessions have new status values handled (default to active if missing)
        for session in self.data.get("sessions", []):
            session.setdefault("last_used", "")
            session.setdefault("projects_created", 0)
            session.setdefault("projects_using", 0)
            session.setdefault("status", "active")
        
        # Ensure projects have new fields
        for project in self.data.get("projects", []):
            project.setdefault("usage_count", 0)
            project.setdefault("max_usage", 20)
            project.setdefault("status", "ready")
            project.setdefault("feature_added", False)
            project.setdefault("mode", "template")
            project.setdefault("project_link", "")
            project.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
            # Migrate old status values to new schema
            if project.get("status") == "active":
                project["status"] = "ready"
    
    def _update_stats(self):
        """Update statistics."""
        sessions = self.data["sessions"]
        projects = self.data["projects"]
        self.data["stats"] = {
            "total_sessions": len(sessions),
            "active_sessions": len([s for s in sessions if s.get("status") == "active"]),
            "on_hold_sessions": len([s for s in sessions if s.get("status") == "on_hold"]),
            "released_sessions": len([s for s in sessions if s.get("status") == "released"]),
            "red_sessions": len([s for s in sessions if s.get("status") == "red"]),
            "truly_red_sessions": len([s for s in sessions if s.get("status") == "truly_red"]),
            "total_projects": len(projects),
            "ready_projects": len([p for p in projects if p.get("status") == "ready"]),
            "in_use_projects": len([p for p in projects if p.get("status") == "in_use"]),
            "done_projects": len([p for p in projects if p.get("status") == "done"]),
            "active_miners": sum(p.get("usage_count", 0) for p in projects)
        }
    
    # SESSION METHODS
    
    def add_session(self, session_id: str, email: str, status: str = "active") -> Dict:
        """Add a new session."""
        session = {
            "id": session_id,
            "email": email,
            "status": status,  # active, on_hold, released, red
            "last_used": datetime.utcnow().isoformat() + "Z",
            "projects_created": 0,
            "projects_using": 0
        }
        
        # Check if exists
        existing = self.get_session(session_id)
        if existing:
            print(f"⚠️  Session {session_id} already exists, updating...")
            self.update_session(session_id, status=status, email=email)
            return existing
        
        self.data["sessions"].append(session)
        print(f"✅ Added session {session_id} ({email}) status={status}")
        return session
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session by ID."""
        for session in self.data["sessions"]:
            if session["id"] == session_id:
                return session
        return None
    
    def update_session(self, session_id: str, **kwargs) -> bool:
        """Update session fields."""
        session = self.get_session(session_id)
        if not session:
            print(f"❌ Session {session_id} not found")
            return False
        
        for key, value in kwargs.items():
            session[key] = value
        
        session["last_used"] = datetime.utcnow().isoformat() + "Z"
        print(f"✅ Updated session {session_id}: {kwargs}")
        return True
    
    def set_session_status(self, session_id: str, status: str) -> bool:
        """Set session status: active, red, truly_red."""
        valid_statuses = ["active", "red", "truly_red"]
        if status not in valid_statuses:
            print(f"❌ Invalid status: {status}. Must be one of {valid_statuses}")
            return False
        return self.update_session(session_id, status=status)
    
    def mark_session_red(self, session_id: str, reason: str = "") -> bool:
        """Mark session as red (expired/blocked)."""
        return self.update_session(session_id, status="red", flag_reason=reason)
    
    def get_active_sessions(self) -> List[Dict]:
        """Get all active (non-flagged) sessions."""
        return [s for s in self.data["sessions"] if s.get("status") in ["active", "on_hold"]]
    
    def get_released_sessions(self) -> List[Dict]:
        """Get sessions ready for mining (released)."""
        return [s for s in self.data["sessions"] if s.get("status") == "released"]
    
    def get_sessions_for_mining(self) -> List[Dict]:
        """Get sessions that can be used for mining (released with projects)."""
        released = self.get_released_sessions()
        result = []
        for s in released:
            # Check if session has ready projects
            projects = [p for p in self.data["projects"] 
                       if p.get("created_by") == s["id"] 
                       and p.get("status") == "ready"
                       and p.get("feature_added", False)]
            if projects:
                result.append(s)
        return result
    
    # PROJECT METHODS
    
    def add_project(self, project: Dict) -> Dict:
        """Add a new project."""
        if "project_id" not in project:
            raise ValueError("Project must have 'project_id'")
        
        # Check if exists
        existing = self.get_project(project["project_id"])
        if existing:
            print(f"⚠️  Project {project['project_id']} already exists")
            return existing
        
        # Set defaults
        project.setdefault("usage_count", 0)
        project.setdefault("max_usage", 20)
        project.setdefault("status", "ready")  # ready, in_use, done, dead
        project.setdefault("feature_added", False)
        project.setdefault("mode", "template")  # template, remix, invite
        project.setdefault("project_link", "")  # public URL
        project.setdefault("created_at", datetime.utcnow().isoformat() + "Z")
        
        self.data["projects"].append(project)
        print(f"✅ Added project {project['project_id']} (status={project['status']}, feature={project['feature_added']}, mode={project['mode']})")
        return project
    
    def get_project(self, project_id: str) -> Optional[Dict]:
        """Get project by ID."""
        for project in self.data["projects"]:
            if project["project_id"] == project_id:
                return project
        return None
    
    def get_project_with_lowest_usage(self) -> Optional[Dict]:
        """Get project with lowest usage_count that's not maxed out (ANY session)."""
        active_projects = [p for p in self.data["projects"] 
                          if p.get("status") in ["ready", "in_use"] 
                          and p.get("usage_count", 0) < p.get("max_usage", 20)]
        
        if not active_projects:
            print("❌ No available projects (all maxed out or dead)")
            return None
        
        # Sort by usage_count
        active_projects.sort(key=lambda x: x.get("usage_count", 0))
        best = active_projects[0]
        print(f"✅ Selected project {best['project_id']} (usage: {best['usage_count']}/{best['max_usage']})")
        return best
    
    def get_project_for_session(self, session_id: str) -> Optional[Dict]:
        """Get project with lowest usage that was created by this specific session."""
        session_projects = [p for p in self.data["projects"] 
                           if p.get("status") in ["ready", "in_use"] 
                           and p.get("created_by") == session_id
                           and p.get("usage_count", 0) < p.get("max_usage", 20)]
        
        if not session_projects:
            print(f"❌ No available projects for {session_id} (create projects with script2 first)")
            return None
        
        # Sort by usage_count
        session_projects.sort(key=lambda x: x.get("usage_count", 0))
        best = session_projects[0]
        print(f"✅ Selected project {best['project_id']} created by {session_id} (usage: {best['usage_count']}/{best['max_usage']})")
        return best
    
    def get_account_linked_project(self, session_id: str) -> Optional[Dict]:
        """Get any usable project owned by this session (linked or not - login fallback covers stale sessions)."""
        linked = [p for p in self.data["projects"]
                  if p.get("created_by") == session_id
                  and p.get("status") in ["ready", "in_use"]
                  and p.get("usage_count", 0) < p.get("max_usage", 20)]
        
        if not linked:
            print(f"❌ No account-linked project for {session_id} (create one with script2 first)")
            return None
        
        linked.sort(key=lambda x: x.get("usage_count", 0))
        best = linked[0]
        print(f"✅ Selected account-linked project {best['project_id']} (usage: {best['usage_count']}/{best['max_usage']})")
        return best
    
    def get_ready_project_for_session(self, session_id: str) -> Optional[Dict]:
        """Get project with feature_added=True, status=ready for this session."""
        ready_projects = [p for p in self.data["projects"] 
                         if p.get("status") == "ready" 
                         and p.get("feature_added", False)
                         and p.get("created_by") == session_id]
        
        if not ready_projects:
            print(f"❌ No ready projects with feature for {session_id}")
            return None
        
        ready_projects.sort(key=lambda x: x.get("usage_count", 0))
        best = ready_projects[0]
        print(f"✅ Selected ready project {best['project_id']} for {session_id} (usage: {best['usage_count']}/{best['max_usage']})")
        return best
    
    def increment_usage(self, project_id: str) -> bool:
        """Increment project usage_count."""
        project = self.get_project(project_id)
        if not project:
            print(f"❌ Project {project_id} not found")
            return False
        
        project["usage_count"] = project.get("usage_count", 0) + 1
        print(f"✅ Incremented {project_id} usage: {project['usage_count']}/{project.get('max_usage', 20)}")
        
        # Update status based on usage
        if project["usage_count"] >= project.get("max_usage", 20):
            project["status"] = "dead"
            print(f"⚠️  Project {project_id} is now DEAD (maxed out)")
        elif project.get("status") == "ready":
            project["status"] = "in_use"
            print(f"📈 Project {project_id} now IN_USE")
        
        return True
    
    def set_project_status(self, project_id: str, status: str) -> bool:
        """Set project status: ready, in_use, done, dead."""
        valid_statuses = ["ready", "in_use", "done", "dead"]
        if status not in valid_statuses:
            print(f"❌ Invalid status: {status}. Must be one of {valid_statuses}")
            return False
        
        project = self.get_project(project_id)
        if not project:
            print(f"❌ Project {project_id} not found")
            return False
        
        project["status"] = status
        print(f"✅ Project {project_id} status: {status}")
        return True
    
    def mark_feature_added(self, project_id: str, project_link: str = "", cmd_name: str = "doc") -> bool:
        """Mark project as having feature added with public link."""
        project = self.get_project(project_id)
        if not project:
            print(f"❌ Project {project_id} not found")
            return False
        
        project["feature_added"] = True
        project["cmd_name"] = cmd_name
        if project_link:
            project["project_link"] = project_link
        project["status"] = "ready"
        print(f"✅ Project {project_id} marked as FEATURE_ADDED (cmd={cmd_name})")
        return True
    
    def mark_project_dead(self, project_id: str) -> bool:
        """Mark project as dead."""
        project = self.get_project(project_id)
        if not project:
            return False
        
        project["status"] = "dead"
        print(f"⚠️  Marked project {project_id} as DEAD")
        return True
    
    # UTILITY
    
    def print_stats(self):
        """Print database statistics."""
        stats = self.data["stats"]
        print("\n" + "=" * 60)
        print("📊 CHIMERA DATABASE STATS")
        print("=" * 60)
        print(f"Sessions: {stats.get('active_sessions', 0)} active, {stats.get('red_sessions', 0)} red, {stats.get('truly_red_sessions', 0)} truly_red")
        print(f"Projects: {stats.get('total_projects', 0)} total ({stats.get('ready_projects', 0)} ready, {stats.get('in_use_projects', 0)} in_use, {stats.get('done_projects', 0)} done)")
        print(f"Miners: {stats.get('active_miners', 0)} active")
        print("=" * 60 + "\n")
    
    def print_all(self):
        """Print all sessions and projects."""
        print("\n=== SESSIONS ===")
        for s in self.data["sessions"]:
            print(f"  {s['id']}: {s['email']} status={s['status']} created={s['projects_created']} using={s['projects_using']}")
        
        print("\n=== PROJECTS ===")
        for p in self.data["projects"]:
            print(f"  {p['project_id']}: created_by={p.get('created_by')} status={p.get('status')} feature={p.get('feature_added')} mode={p.get('mode')} usage={p.get('usage_count')}/{p.get('max_usage')}")


# Convenience functions
def load_db() -> MegaDB:
    """Load database from Mega."""
    db = MegaDB()
    db.sync_from_mega()
    return db


def save_db(db: MegaDB):
    """Save database to Mega."""
    db.sync_to_mega()


if __name__ == "__main__":
    print("🧪 Testing Mega DB...")
    
    # Test
    db = load_db()
    db.print_stats()
    db.print_all()
    
    # Add test session
    db.add_session("session-test", "test@example.com", "active")
    
    # Add test project
    db.add_project({
        "project_id": "test-123",
        "invite_link": "https://lovable.dev/projects/test-123?magic_link=xxx",
        "chat_url": "https://lovable.dev/projects/test-123",
        "preview_url": "https://lovable.dev/projects/test-123/preview",
        "created_by": "session-test"
    })
    
    # Test usage
    db.increment_usage("test-123")
    
    # Save
    save_db(db)
    
    print("\n✅ Mega DB test complete!")