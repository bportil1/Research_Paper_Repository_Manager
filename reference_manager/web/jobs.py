from __future__ import annotations
import threading, traceback, uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable

JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()

def create_job(kind: str, message: str = "Queued") -> str:
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"id":job_id,"kind":kind,"status":"queued","message":message,"current":0,"total":0,"result":None,"error":"","created_at":datetime.now().isoformat(),"updated_at":datetime.now().isoformat()}
    return job_id

def update_job(job_id: str, **changes: Any) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update(changes); JOBS[job_id]["updated_at"] = datetime.now().isoformat()

def get_job(job_id: str) -> dict[str, Any] | None:
    with JOBS_LOCK:
        return dict(JOBS[job_id]) if job_id in JOBS else None

def run_job(job_id: str, fn: Callable[[], Any]) -> None:
    def wrapped():
        update_job(job_id, status="running")
        try:
            update_job(job_id, status="done", message="Complete", result=fn())
        except Exception as exc:
            update_job(job_id,status="error",error=f"{type(exc).__name__}: {exc}",error_details=traceback.format_exc(),message="Failed — open details for the exact error")
    JOB_EXECUTOR.submit(wrapped)
