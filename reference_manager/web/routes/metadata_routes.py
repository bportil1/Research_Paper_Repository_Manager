from __future__ import annotations

from flask import Blueprint, jsonify, request

from reference_manager.web.jobs import create_job, run_job, update_job
from reference_manager.web.routes.common import error_response, get_manager

bp = Blueprint("metadata_api", __name__)


@bp.post("/api/metadata/extract")
def extract_metadata():
    try:
        manager = get_manager()
        data = request.get_json(silent=True) or {}
        paper_id = str(data.get("paper_id", "")) or None
        job_id = create_job("metadata_extract", "Preparing PDF metadata extraction")

        def task():
            def progress(current: int, total: int, message: str) -> None:
                update_job(job_id, current=current, total=total, message=message)

            return manager.extract_metadata(paper_id, progress=progress)

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)


@bp.get("/api/duplicates")
def duplicates():
    try:
        groups = get_manager().find_duplicates()
        return jsonify({"groups": groups, "count": len(groups)})
    except Exception as exc:
        return error_response(exc)
