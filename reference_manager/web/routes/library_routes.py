from __future__ import annotations

from flask import Blueprint, jsonify, request

from reference_manager.web.jobs import create_job, run_job, update_job
from reference_manager.web.routes.common import error_response, get_manager

bp = Blueprint("library_api", __name__)


@bp.get("/api/library")
def get_library():
    try:
        manager = get_manager()
        return jsonify({"library_root": str(manager.root), "rows": manager.list_papers()})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/sync/start")
def start_sync():
    try:
        manager = get_manager()
        data = request.get_json(silent=True) or {}
        detect_moves = bool(data.get("detect_moves", True))
        extract_titles = bool(data.get("extract_titles", True))
        job_id = create_job("sync", "Preparing library scan")

        def task():
            def progress(current: int, total: int, message: str) -> None:
                update_job(job_id, current=current, total=total, message=message)

            return manager.sync(
                detect_moves=detect_moves,
                extract_titles=extract_titles,
                progress=progress,
            )

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/report")
def save_report():
    try:
        rows = request.get_json(force=True).get("rows", [])
        if not isinstance(rows, list):
            return jsonify({"error": "rows must be a list."}), 400
        count = get_manager().save_papers(rows)
        return jsonify({"ok": True, "rows_written": count})
    except Exception as exc:
        return error_response(exc)
