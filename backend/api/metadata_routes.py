from __future__ import annotations

from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from backend.api.common import error_response
from backend.config import get_library_root
from backend.jobs.manager import create_job, run_job, update_job
from backend.library.report import LIBRARY_WRITE_LOCK, find_row, read_report, write_report_atomic
from backend.services.duplicates import find_duplicate_groups
from backend.services.pdf_metadata import extract_pdf_metadata
from backend.utils.text import is_missing_title

bp = Blueprint("metadata_api", __name__)


@bp.post("/api/metadata/extract")
def extract_metadata():
    try:
        root = get_library_root()
        data = request.get_json(silent=True) or {}
        paper_id = str(data.get("paper_id", ""))
        job_id = create_job("metadata_extract", "Preparing PDF metadata extraction")

        def task():
            with LIBRARY_WRITE_LOCK:
                rows = read_report(root)
                if not rows:
                    raise RuntimeError("The current paper_report.csv contains no records; extraction was cancelled without writing.")
                original_ids = {row.get("PaperID", "") for row in rows if row.get("PaperID")}
                targets = [find_row(rows, paper_id)] if paper_id else [row for row in rows if row.get("FileState") == "Present"]
                updated = 0
                errors = []
                for index, row in enumerate(targets, 1):
                    update_job(job_id, current=index, total=len(targets), message=f"Reading {row.get('Filename', '')}")
                    try:
                        path = Path(row["Path"])
                        if not path.exists():
                            errors.append({"paper_id": row.get("PaperID"), "error": f"File not found: {path}"})
                            continue
                        metadata = extract_pdf_metadata(path)
                        changed = False
                        for key, value in metadata.items():
                            if value and (not row.get(key) or (key == "Title" and is_missing_title(row.get(key, "")))):
                                row[key] = value
                                changed = True
                        if changed:
                            row["ModifiedDate"] = datetime.now().isoformat()
                            updated += 1
                    except Exception as exc:
                        errors.append({"paper_id": row.get("PaperID"), "error": f"{type(exc).__name__}: {exc}"})
                write_report_atomic(root, rows, "extract_pdf_metadata", expected_ids=original_ids)
                return {
                    "updated": updated,
                    "processed": len(targets),
                    "errors": errors[:50],
                    "rows_preserved": len(rows),
                }

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)


@bp.get("/api/duplicates")
def duplicates():
    try:
        groups = find_duplicate_groups(read_report(get_library_root()))
        return jsonify({"groups": groups, "count": len(groups)})
    except Exception as exc:
        return error_response(exc)
