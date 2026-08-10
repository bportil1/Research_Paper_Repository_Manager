from __future__ import annotations

import io

from flask import Blueprint, jsonify, request

from reference_manager.web.jobs import create_job, run_job, update_job
from reference_manager.web.routes.common import error_response, get_manager

bp = Blueprint("import_api", __name__)


@bp.post("/api/csv/import")
def import_csv():
    try:
        manager = get_manager()
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "Choose a CSV file."}), 400
        create_unmatched = str(request.form.get("create_unmatched", "false")).lower() == "true"
        payload = uploaded.read()
        job_id = create_job("csv_import", "Preparing CSV metadata transfer")

        def task():
            return manager.import_csv(io.BytesIO(payload), create_unmatched=create_unmatched)

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/bib/import")
def import_bibtex():
    try:
        manager = get_manager()
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "Choose a .bib file."}), 400
        text = uploaded.read().decode("utf-8", errors="replace")
        job_id = create_job("bib_import", "Preparing BibTeX import")

        def task():
            def progress(current: int, total: int, message: str) -> None:
                update_job(job_id, current=current, total=total, message=message)

            return manager.import_bibtex_text(text, progress=progress)

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)
