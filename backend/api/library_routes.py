from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from backend.api.common import error_response
from backend.config import get_library_root
from backend.jobs.manager import create_job, run_job, update_job
from backend.library.report import read_report, write_report_atomic
from backend.library.scanner import reconcile_library
from backend.services.pdf_metadata import extract_pdf_metadata
from backend.utils.text import is_missing_title

bp = Blueprint("library_api", __name__)


@bp.get("/api/library")
def get_library():
    try:
        root = get_library_root()
        return jsonify({"library_root": str(root), "rows": read_report(root)})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/sync/start")
def start_sync():
    try:
        root = get_library_root()
        data = request.get_json(silent=True) or {}
        detect_moves = bool(data.get("detect_moves", True))
        extract_titles = bool(data.get("extract_titles", True))
        job_id = create_job("sync", "Preparing library scan")

        def task():
            def progress(current: int, total: int, message: str) -> None:
                update_job(job_id, current=current, total=total, message=message)

            rows, summary = reconcile_library(
                root,
                compute_hashes=detect_moves,
                progress=progress,
            )

            if extract_titles:
                targets = [
                    row for row in rows
                    if row.get("FileState") == "Present"
                    and is_missing_title(row.get("Title", ""))
                ]
                for index, row in enumerate(targets, 1):
                    update_job(
                        job_id,
                        current=index,
                        total=len(targets),
                        message=f"Extracting title: {row.get('Filename', '')}",
                    )
                    try:
                        metadata = extract_pdf_metadata(Path(row["Path"]))
                        for key, value in metadata.items():
                            if value and (
                                not row.get(key)
                                or (key == "Title" and is_missing_title(row.get(key, "")))
                            ):
                                row[key] = value
                    except Exception:
                        continue

            expected_ids = {
                row.get("PaperID", "")
                for row in read_report(root)
                if row.get("PaperID")
            }
            write_report_atomic(
                root,
                rows,
                "sync_library",
                expected_ids=expected_ids,
            )
            return {
                key: value
                for key, value in summary.items()
                if not key.endswith("_rows")
            }

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/report")
def save_report():
    try:
        root = get_library_root()
        rows = request.get_json(force=True).get("rows", [])
        if not isinstance(rows, list):
            return jsonify({"error": "rows must be a list."}), 400
        current = read_report(root)
        expected_ids = {
            row.get("PaperID", "")
            for row in current
            if row.get("PaperID")
        }
        write_report_atomic(
            root,
            rows,
            "save_metadata",
            expected_ids=expected_ids,
        )
        return jsonify({"ok": True, "rows_written": len(rows)})
    except Exception as exc:
        return error_response(exc)
