from __future__ import annotations

import csv
import json
import os
import shutil

from flask import Blueprint, jsonify

from backend.api.common import error_response
from backend.config import get_library_root
from backend.library.paths import manager_dir, report_path
from backend.library.report import LIBRARY_WRITE_LOCK, normalize_row
from backend.services.checkpoints import list_checkpoints, now_stamp
from backend.services.logging_service import log_operation

bp = Blueprint("checkpoint_api", __name__)


@bp.get("/api/history")
def history():
    try:
        root = get_library_root()
        path = manager_dir(root) / "logs" / "operations.jsonl"
        records = []
        if path.exists():
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return jsonify({"history": records[-100:][::-1]})
    except Exception as exc:
        return error_response(exc)


@bp.get("/api/checkpoints")
def checkpoints():
    try:
        return jsonify({"checkpoints": list_checkpoints(get_library_root())})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/checkpoints/restore-latest")
def restore_latest():
    try:
        root = get_library_root()
        with LIBRARY_WRITE_LOCK:
            base = manager_dir(root) / "checkpoints"
            candidates = sorted(
                [path for path in base.iterdir() if path.is_dir() and (path / "paper_report.csv").exists()],
                reverse=True,
            ) if base.exists() else []
            if not candidates:
                return jsonify({"error": "No checkpoint containing paper_report.csv was found."}), 404

            latest = candidates[0]
            source = latest / "paper_report.csv"
            emergency = base / f"before_restore_{now_stamp()}"
            emergency.mkdir(parents=True, exist_ok=True)
            current = report_path(root)
            if current.exists():
                shutil.copy2(current, emergency / "paper_report.csv")

            temp = root / "paper_report.restore.tmp"
            shutil.copy2(source, temp)
            with temp.open("r", encoding="utf-8-sig", newline="") as handle:
                restored_rows = [normalize_row(dict(row)) for row in csv.DictReader(handle)]
            if not restored_rows:
                temp.unlink(missing_ok=True)
                raise RuntimeError("The latest checkpoint report is empty; restore was cancelled.")
            os.replace(temp, current)
            log_operation(root, "restore_latest_report_checkpoint", {
                "checkpoint": latest.name,
                "rows_restored": len(restored_rows),
            })
            return jsonify({
                "ok": True,
                "checkpoint": latest.name,
                "rows_restored": len(restored_rows),
            })
    except Exception as exc:
        return error_response(exc)
