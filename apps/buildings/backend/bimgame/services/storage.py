"""Project storage: JSON files on disk (source of truth) + SQLite index/jobs.

Saving is atomic (temp file + ``os.replace``) and keeps one ``.bak`` copy so a
crash mid-save or a corrupted file never loses the previous good version.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import sqlite3
import threading
from pathlib import Path

from pydantic import ValidationError

from ..config import Settings
from ..schema import Project, utcnow
from ..utils.errors import AppError, NotFound


BACKUP_RE = re.compile(r"^project_\d{8}_\d{6}(_[a-z][0-9]{0,8})?\.json$")


class ProjectStore:
    BACKUP_EVERY = 300   # seconds between automatic snapshots (taken when a save replaces the previous version)
    BACKUP_KEEP = 30     # newest snapshots kept (manual ones too)

    def __init__(self, settings: Settings):
        self.s = settings
        self.s.projects_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.s.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects(
                    id TEXT PRIMARY KEY, name TEXT, updated_at TEXT, size_bytes INTEGER, elements INTEGER);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, project_id TEXT, kind TEXT, status TEXT,
                    created_at TEXT, started_at TEXT, finished_at TEXT, params TEXT, result TEXT, error TEXT);
                """
            )

    # paths ---------------------------------------------------------------
    def dir(self, pid: str) -> Path:
        if not pid.replace("_", "").isalnum():
            raise AppError("Invalid project id", "storage.dir", f"'{pid}' has unsafe characters", "Use ids from /api/projects")
        return self.s.projects_dir / pid

    def file(self, pid: str) -> Path:
        return self.dir(pid) / "project.json"

    # CRUD ----------------------------------------------------------------
    def save(self, p: Project) -> Project:
        with self._lock:
            p.updated_at = utcnow()
            d = self.dir(p.id)
            d.mkdir(parents=True, exist_ok=True)
            data = p.model_dump_json(indent=1)
            tmp = d / "project.json.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:      # flush to disk before the atomic rename: a power cut never leaves a half-written project
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            target = self.file(p.id)
            if target.exists():
                shutil.copy2(target, d / "project.json.bak")
                self._auto_snapshot(p.id, target)
            os.replace(tmp, target)
            with self._db:
                self._db.execute(
                    "INSERT INTO projects(id,name,updated_at,size_bytes,elements) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET name=excluded.name, updated_at=excluded.updated_at, "
                    "size_bytes=excluded.size_bytes, elements=excluded.elements",
                    (p.id, p.name, p.updated_at, len(data.encode()), len(p.elements)),
                )
            return p

    # backups ---------------------------------------------------------------
    def backups_dir(self, pid: str) -> Path:
        return self.dir(pid) / "backups"

    def _auto_snapshot(self, pid: str, source: Path) -> None:
        d = self.backups_dir(pid)
        try:
            latest = max((f.stat().st_mtime for f in d.glob("project_*.json")), default=0.0)
            if time.time() - latest >= self.BACKUP_EVERY:
                self._write_snapshot(pid, source)
        except OSError:
            pass  # a failed backup must never fail a save

    def _write_snapshot(self, pid: str, source: Path, tag: str = "") -> str:
        d = self.backups_dir(pid)
        d.mkdir(parents=True, exist_ok=True)
        base = time.strftime("project_%Y%m%d_%H%M%S", time.gmtime())
        tag = f"{tag or '_a'}{int(time.time() * 1000) % 1000:03d}"      # ms keep names unique even inside one second
        name, n = f"{base}{tag}.json", 0
        while (d / name).exists():
            n += 1
            name = f"{base}{tag}{n}.json"
        shutil.copyfile(source, d / name)          # copyfile (not copy2): the snapshot's mtime is its creation time
        files = sorted(d.glob("project_*.json"), key=lambda f: (f.stat().st_mtime_ns, f.name))
        for old in [f for f in files if f.name != name][: max(0, len(files) - self.BACKUP_KEEP)]:
            old.unlink(missing_ok=True)
        return name

    def snapshot(self, pid: str, tag: str = "_m") -> str:
        """Manual snapshot of the project as saved on disk."""
        with self._lock:
            if not self.exists(pid):
                raise NotFound("Project not found", "storage.snapshot", pid, "List projects first")
            return self._write_snapshot(pid, self.file(pid), tag)

    def list_backups(self, pid: str) -> list[dict]:
        d = self.backups_dir(pid)
        out = []
        for f in sorted(d.glob("project_*.json"), key=lambda f: (f.stat().st_mtime_ns, f.name), reverse=True) if d.exists() else []:
            if not BACKUP_RE.match(f.name):
                continue
            st = f.stat()
            try:
                n = len(json.loads(f.read_text(encoding="utf-8")).get("elements", []))
            except (ValueError, OSError):
                n = None
            out.append({"name": f.name, "size_bytes": st.st_size, "modified": st.st_mtime, "elements": n, "manual": bool(re.search(r"_[mb]\d*\.json$", f.name))})
        return out

    def _backup_file(self, pid: str, name: str) -> Path:
        f = self.backups_dir(pid) / name
        if not BACKUP_RE.match(name) or not f.exists():
            raise NotFound("Backup not found", "storage.backup", name, "List backups first")
        return f

    def restore(self, pid: str, name: str) -> Project:
        """Replace the project with a backup (the current state is snapshotted first, so a restore can be undone)."""
        with self._lock:
            f = self._backup_file(pid, name)
            try:
                p = Project.model_validate_json(f.read_text(encoding="utf-8"))
            except (ValidationError, ValueError) as e:
                raise AppError("Backup is not a valid project", "storage.restore", str(e)[:300], "Pick another backup", status=422) from e
            cur = self.load(pid)
            self.snapshot(pid, "_b")
            p.id, p.build_history = pid, cur.build_history
            return self.save(p)

    def delete_backup(self, pid: str, name: str) -> None:
        with self._lock:
            self._backup_file(pid, name).unlink()

    def load(self, pid: str) -> Project:
        f = self.file(pid)
        if not f.exists():
            raise NotFound("Project not found", "storage.load", f"no file for id {pid}", "List projects with GET /api/projects")
        for candidate in (f, f.with_suffix(".json.bak")):
            if not candidate.exists():
                continue
            try:
                return Project.model_validate_json(candidate.read_text(encoding="utf-8"))
            except (ValidationError, ValueError, OSError):
                continue
        raise AppError(
            "Project file is corrupted and no valid backup exists", "storage.load",
            f"{f} and its .bak failed validation", "Restore from your own backup or delete the project", status=422,
        )

    def append_build(self, pid: str, rec) -> None:
        """Server-owned build history: reload, append, save atomically under the store lock."""
        with self._lock:
            p = self.load(pid)
            p.build_history = (p.build_history + [rec])[-50:]
            self.save(p)

    def exists(self, pid: str) -> bool:
        return self.file(pid).exists()

    def list(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]

    def delete(self, pid: str) -> None:
        with self._lock:
            d = self.dir(pid)
            if not d.exists():
                raise NotFound("Project not found", "storage.delete", pid, "List projects first")
            shutil.rmtree(d)
            with self._db:
                self._db.execute("DELETE FROM projects WHERE id=?", (pid,))
                self._db.execute("DELETE FROM jobs WHERE project_id=?", (pid,))

    # jobs ----------------------------------------------------------------
    def job_put(self, job: dict) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO jobs(id,project_id,kind,status,created_at,started_at,finished_at,params,result,error) "
                "VALUES(:id,:project_id,:kind,:status,:created_at,:started_at,:finished_at,:params,:result,:error) "
                "ON CONFLICT(id) DO UPDATE SET status=excluded.status, started_at=excluded.started_at, "
                "finished_at=excluded.finished_at, result=excluded.result, error=excluded.error",
                {
                    **{k: job.get(k) for k in ("id", "project_id", "kind", "status", "created_at", "started_at", "finished_at")},
                    "error": json.dumps(job["error"]) if job.get("error") is not None else None,
                    "params": json.dumps(job.get("params") or {}),
                    "result": json.dumps(job.get("result")) if job.get("result") is not None else None,
                },
            )
            if job.get("status") in ("succeeded", "failed", "cancelled"):
                self._prune_jobs()

    JOBS_KEEP = 300

    def _prune_jobs(self) -> None:
        """Finished jobs carry big result blobs; keep only the newest JOBS_KEEP (called under the lock)."""
        self._db.execute(
            "DELETE FROM jobs WHERE status NOT IN ('queued','running') AND id NOT IN "
            "(SELECT id FROM jobs WHERE status NOT IN ('queued','running') ORDER BY created_at DESC LIMIT ?)", (self.JOBS_KEEP,))

    def job_get(self, jid: str) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["params"] = json.loads(d["params"] or "{}")
        d["result"] = json.loads(d["result"]) if d["result"] else None
        d["error"] = json.loads(d["error"]) if d["error"] else None
        return d

    def mark_interrupted_jobs(self) -> int:
        """On startup: jobs left queued/running by a previous crash cannot still be running."""
        with self._lock, self._db:
            cur = self._db.execute(
                "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE status IN ('queued','running')",
                (json.dumps({"what": "Server restarted while job was active", "where": "jobs.startup", "why": "the process stopped mid-job", "fix": "Submit the build again"}), utcnow()),
            )
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._db.close()
