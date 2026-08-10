from __future__ import annotations

from flask import Blueprint, jsonify

from reference_manager.web.jobs import get_job

bp = Blueprint("job_api", __name__)


@bp.get("/api/jobs/<job_id>")
def get_job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found."}), 404
    return jsonify(job)
