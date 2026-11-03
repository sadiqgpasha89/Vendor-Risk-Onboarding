"""Background jobs: run long case steps (several model calls) off the HTTP request.

The job row is the source of truth (`jobs` table); the thread pool is only the executor. A replica that dies mid-job leaves the row RUNNING;
`reap()` (called by the sweep) marks such rows FAILED(orphaned). Re-submitting is safe: every agent step is idempotent (R6) and case mutations
are serialised by the per-case lock, so a retried job resumes where the state machine stands.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Callable

from .obs import log
from .store import Store
from .util import iso, new_id, now


class JobRunner:
    def __init__(self, store: Store, workers: int = 4, orphan_after_s: int = 900):
        self.store, self.orphan_after = store, orphan_after_s
        self.pool = ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="vro-job")
        self._lock = threading.Lock()

    def submit(self, tenant_id: str, case_id: str, kind: str, requested_by: str, fn: Callable[[], dict]) -> dict:
        # one in-flight job per (case, kind): a second click returns the first job instead of queueing a duplicate
        with self._lock:
            live = self.store.one("SELECT * FROM jobs WHERE tenant_id=? AND case_id=? AND kind=? AND status IN ('QUEUED','RUNNING') ORDER BY created_at DESC",
                                  (tenant_id, case_id, kind))
            if live:
                return live
            jid = new_id("job_")
            self.store.insert("jobs", {"job_id": jid, "tenant_id": tenant_id, "case_id": case_id, "kind": kind, "status": "QUEUED",
                                       "requested_by": requested_by, "created_at": iso(now())})
        self.pool.submit(self._run, tenant_id, jid, fn)
        return self.store.get("jobs", "job_id", jid)

    def _run(self, tenant_id: str, jid: str, fn: Callable[[], dict]) -> None:
        with self.store.tenant_scope(tenant_id):
            self.store.update("jobs", "job_id", jid, {"status": "RUNNING", "started_at": iso(now())})
            try:
                res = fn()
                self.store.update("jobs", "job_id", jid, {"status": "DONE", "result": res, "finished_at": iso(now())})
            except Exception as e:  # noqa: BLE001
                log("job_failed", job_id=jid, error=type(e).__name__)
                # exception TYPE and a short message only: messages can carry user data, never a traceback into the DB
                self.store.update("jobs", "job_id", jid, {"status": "FAILED", "error": f"{type(e).__name__}: {str(e)[:200]}", "finished_at": iso(now())})

    def reap(self, tenant_id: str) -> int:
        cutoff = iso(now() - timedelta(seconds=self.orphan_after))
        rows = self.store.query("SELECT job_id FROM jobs WHERE tenant_id=? AND status IN ('QUEUED','RUNNING') AND created_at < ?", (tenant_id, cutoff))
        for r in rows:
            self.store.update("jobs", "job_id", r["job_id"], {"status": "FAILED", "error": "orphaned (worker lost); re-submit", "finished_at": iso(now())})
        return len(rows)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=False)
