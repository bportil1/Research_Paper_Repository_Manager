from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from backend.api.common import error_response
from backend.config import get_library_root
from backend.library.paths import manager_dir
from backend.library.report import find_row, read_report, write_report_atomic
from backend.services.checkpoints import create_checkpoint, now_stamp
from backend.services.logging_service import log_operation

bp = Blueprint("paper_api", __name__)


def _open_with_system(path: Path) -> None:
    """Open a local file or directory with the operating-system default app."""
    if sys.platform.startswith("linux"):
        command = ["xdg-open", str(path)]
    elif sys.platform == "darwin":
        command = ["open", str(path)]
    elif sys.platform.startswith("win"):
        command = ["explorer", str(path)]
    else:
        raise RuntimeError(f"Opening local paths is unsupported on {sys.platform}.")

    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required system opener was not found: {command[0]}") from exc


def _validated_library_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser().resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("The requested path is outside the configured library.") from exc
    return path



@bp.post("/api/papers/move")
def move_paper():
    try:
        root = get_library_root()
        data = request.get_json(force=True)
        paper_id = str(data.get("paper_id", ""))
        destination_topic = str(data.get("destination_topic", "")).strip()
        if not destination_topic or "/" in destination_topic or "\\" in destination_topic:
            return jsonify({"error": "Enter a valid destination topic without path separators."}), 400

        rows = read_report(root)
        row = find_row(rows, paper_id)
        if row["FileState"] != "Present":
            return jsonify({"error": "Only present PDFs can be moved."}), 400
        src = Path(row["Path"]).resolve()
        if not src.exists():
            return jsonify({"error": f"Source PDF does not exist: {src}"}), 400

        dst_dir = root / destination_topic
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if dst.exists() and dst.resolve() != src:
            return jsonify({"error": f"Destination already contains {dst.name}."}), 409

        create_checkpoint(root, "move_paper", [src])
        shutil.move(str(src), str(dst))
        row.update({
            "Topic": destination_topic,
            "Path": str(dst.resolve()),
            "Filename": dst.name,
            "FileState": "Present",
        })
        write_report_atomic(root, rows, "move_paper_csv_update", checkpoint=False)
        log_operation(root, "move_paper", {
            "paper_id": paper_id,
            "from": str(src),
            "to": str(dst),
        })
        return jsonify({"ok": True, "row": row})
    except KeyError as exc:
        return error_response(exc, 404)
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/papers/archive")
def archive_paper():
    try:
        root = get_library_root()
        paper_id = str(request.get_json(force=True).get("paper_id", ""))
        rows = read_report(root)
        row = find_row(rows, paper_id)
        if row["FileState"] != "Present":
            return jsonify({"error": "Only present PDFs can be archived."}), 400

        src = Path(row["Path"]).resolve()
        if not src.exists():
            return jsonify({"error": f"Source PDF does not exist: {src}"}), 400

        stamp = now_stamp()
        rel = src.relative_to(root)
        dst = manager_dir(root) / "deleted_pdfs" / stamp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        create_checkpoint(root, "archive_paper", [src])
        shutil.move(str(src), str(dst))
        row.update({
            "OriginalPath": str(src),
            "ArchivedAt": datetime.now().isoformat(),
            "Path": str(dst.resolve()),
            "FileState": "Deleted",
        })
        write_report_atomic(root, rows, "archive_paper_csv_update", checkpoint=False)
        log_operation(root, "archive_paper", {
            "paper_id": paper_id,
            "from": str(src),
            "archive": str(dst),
        })
        return jsonify({"ok": True, "row": row})
    except KeyError as exc:
        return error_response(exc, 404)
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/papers/restore")
def restore_paper():
    try:
        root = get_library_root()
        data = request.get_json(force=True)
        paper_id = str(data.get("paper_id", ""))
        destination_topic = str(data.get("destination_topic", "")).strip()
        rows = read_report(root)
        row = find_row(rows, paper_id)
        if row["FileState"] != "Deleted":
            return jsonify({"error": "Only archived PDFs can be restored."}), 400

        src = Path(row["Path"]).resolve()
        if not src.exists():
            return jsonify({"error": f"Archived PDF does not exist: {src}"}), 400

        if destination_topic:
            if "/" in destination_topic or "\\" in destination_topic:
                return jsonify({"error": "Invalid destination topic."}), 400
            dst = root / destination_topic / row["Filename"]
        elif row.get("OriginalPath"):
            dst = Path(row["OriginalPath"]).resolve()
            dst.relative_to(root)
        else:
            dst = root / row["Topic"] / row["Filename"]

        if dst.exists():
            return jsonify({"error": f"Restore destination already exists: {dst}"}), 409
        dst.parent.mkdir(parents=True, exist_ok=True)
        create_checkpoint(root, "restore_paper", [src])
        shutil.move(str(src), str(dst))
        rel = dst.relative_to(root)
        topic = rel.parts[0] if len(rel.parts) > 1 else "Uncategorized"
        row.update({
            "Topic": topic,
            "Path": str(dst.resolve()),
            "Filename": dst.name,
            "FileState": "Present",
            "OriginalPath": "",
            "ArchivedAt": "",
        })
        write_report_atomic(root, rows, "restore_paper_csv_update", checkpoint=False)
        log_operation(root, "restore_paper", {
            "paper_id": paper_id,
            "from": str(src),
            "to": str(dst),
        })
        return jsonify({"ok": True, "row": row})
    except KeyError as exc:
        return error_response(exc, 404)
    except ValueError:
        return jsonify({"error": "Original path is outside the configured library."}), 400
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/papers/open")
def open_paper():
    try:
        root = get_library_root()
        paper_id = str(request.get_json(force=True).get("paper_id", ""))
        row = find_row(read_report(root), paper_id)
        if row.get("FileState") != "Present":
            return jsonify({"error": "Only present PDFs can be opened."}), 400

        path = _validated_library_path(root, row.get("Path", ""))
        if not path.exists() or not path.is_file():
            return jsonify({"error": f"PDF does not exist: {path}"}), 404

        _open_with_system(path)
        return jsonify({"ok": True, "path": str(path)})
    except KeyError as exc:
        return error_response(exc, 404)
    except ValueError as exc:
        return error_response(exc, 400)
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/papers/show-in-folder")
def show_paper_in_folder():
    try:
        root = get_library_root()
        paper_id = str(request.get_json(force=True).get("paper_id", ""))
        row = find_row(read_report(root), paper_id)
        path = _validated_library_path(root, row.get("Path", ""))

        folder = path if path.is_dir() else path.parent
        if not folder.exists() or not folder.is_dir():
            return jsonify({"error": f"Containing folder does not exist: {folder}"}), 404

        _open_with_system(folder)
        return jsonify({"ok": True, "path": str(folder)})
    except KeyError as exc:
        return error_response(exc, 404)
    except ValueError as exc:
        return error_response(exc, 400)
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/topics/open")
def open_topic_folder():
    try:
        root = get_library_root()
        topic = str(request.get_json(force=True).get("topic", "")).strip()
        if not topic or "/" in topic or "\\" in topic:
            return jsonify({"error": "Enter a valid topic without path separators."}), 400

        folder = (root / topic).resolve()
        _validated_library_path(root, str(folder))
        if not folder.exists() or not folder.is_dir():
            return jsonify({"error": f"Topic folder does not exist: {folder}"}), 404

        _open_with_system(folder)
        return jsonify({"ok": True, "path": str(folder)})
    except ValueError as exc:
        return error_response(exc, 400)
    except Exception as exc:
        return error_response(exc)

