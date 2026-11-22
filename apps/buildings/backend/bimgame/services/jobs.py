"""Single-slot job manager: exactly ONE heavy build runs at a time.

Extra submissions wait in a short FIFO queue (bounded); beyond that the API
answers 429 so memory can never be oversubscribed. State is persisted in
SQLite so status survives a page reload and a restart marks interrupted jobs.
"""
from __future__ import annotations

import logging
import queue
import threading
import uuid

from ..schema import utcnow
from ..utils.errors import AppError
from .build import BuildService
from .storage import ProjectStore

log = logging.getLogger("bimgame.jobs")
MAX_QUEUED = 4


class JobManager:
    def __init__(self, store: ProjectStore, builder: BuildService):
        self.store, self.builder = store, builder
        self._q: queue.Queue[str | None] = queue.Queue()
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self.store.mark_interrupted_jobs()
        self._t = threading.Thread(target=self._loop, name="build-worker", daemon=True)
        self._t.start()

    def submit(self, project_id: str, kind: str, params: dict) -> dict:
        if not self.store.exists(project_id):
            from ..utils.errors import NotFound
            raise NotFound("Project not found", "jobs.submit", project_id, "Create or select a project first")
        with self._lock:
            if self._q.qsize() >= MAX_QUEUED:
                raise AppError("Build queue is full", "jobs.submit", f"{MAX_QUEUED} jobs already waiting",
                               "Wait for current builds to finish (one heavy job runs at a time to protect RAM)", status=429)
            jid = uuid.uuid4().hex
            job = {"id": jid, "project_id": project_id, "kind": kind, "status": "queued", "created_at": utcnow(),
                   "started_at": None, "finished_at": None, "params": params, "result": None, "error": None}
            self.store.job_put(job)
            self._cancel[jid] = threading.Event()
            self._q.put(jid)
        return job

    def cancel(self, jid: str) -> dict:
        job = self.get(jid)
        ev = self._cancel.get(jid)
        if job["status"] in ("queued", "running") and ev:
            ev.set()
            if job["status"] == "queued":
                job.update(status="cancelled", finished_at=utcnow())
                self.store.job_put(job)
        return self.get(jid)

    def get(self, jid: str) -> dict:
        from ..utils.errors import NotFound
        j = self.store.job_get(jid)
        if not j:
            raise NotFound("Job not found", "jobs.get", jid, "Check the job id returned by the build request")
        return j

    def active(self) -> dict:
        return {"queued": self._q.qsize(), "running": any(
            (self.store.job_get(j) or {}).get("status") == "running" for j in list(self._cancel))}

    def _loop(self) -> None:
        while True:
            jid = self._q.get()
            if jid is None:
                return
            try:  # the worker thread must survive ANY single-job failure
                self._run_one(jid)
            except Exception:  # noqa: BLE001
                log.exception("job loop error for %s", jid)
                try:
                    j = self.store.job_get(jid)
                    if j and j["status"] in ("queued", "running"):
                        j.update(status="failed", finished_at=utcnow(),
                                 error={"what": "Internal job error", "where": "jobs.loop", "why": "see server log", "fix": "Retry"})
                        self.store.job_put(j)
                except Exception:  # noqa: BLE001
                    log.exception("could not record failure for %s", jid)
            finally:
                self._cancel.pop(jid, None)

    def _run_one(self, jid: str) -> None:
        job = self.store.job_get(jid)
        if not job or job["status"] == "cancelled":
            return
        job.update(status="running", started_at=utcnow())
        self.store.job_put(job)
        try:
            res = self.builder.run(jid, job["project_id"], job["kind"], job["params"], self._cancel[jid])
            job.update(status="succeeded", result=res)
        except AppError as e:
            log.warning("job %s failed: %s | %s", jid, e.what, e.why)
            job.update(status="cancelled" if e.status == 499 else "failed", error=e.to_dict()["error"])
        except Exception as e:  # noqa: BLE001 - never lose a job silently
            log.exception("job %s crashed", jid)
            job.update(status="failed", error={"what": "Unexpected internal error", "where": "jobs.loop",
                                               "why": f"{type(e).__name__}: {e}", "fix": "See server log"})
        job["finished_at"] = utcnow()
        self.store.job_put(job)

    def shutdown(self) -> None:
        self._q.put(None)
        self._t.join(timeout=5)
