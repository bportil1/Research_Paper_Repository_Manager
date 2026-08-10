from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from flask import Blueprint, jsonify, request

from reference_manager.web.routes.common import error_response, get_manager, mapped_error_response

bp = Blueprint("paper_api", __name__)


def _open_with_system(path: Path) -> None:
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
        data = request.get_json(force=True)
        row = get_manager().move_paper(
            str(data.get("paper_id", "")),
            str(data.get("destination_topic", "")),
        )
        return jsonify({"ok": True, "row": row})
    except Exception as exc:
        return mapped_error_response(exc)


@bp.post("/api/papers/archive")
def archive_paper():
    try:
        paper_id = str(request.get_json(force=True).get("paper_id", ""))
        return jsonify({"ok": True, "row": get_manager().archive_paper(paper_id)})
    except Exception as exc:
        return mapped_error_response(exc)


@bp.post("/api/papers/restore")
def restore_paper():
    try:
        data = request.get_json(force=True)
        row = get_manager().restore_paper(
            str(data.get("paper_id", "")),
            str(data.get("destination_topic", "")),
        )
        return jsonify({"ok": True, "row": row})
    except Exception as exc:
        return mapped_error_response(exc)


@bp.post("/api/papers/open")
def open_paper():
    try:
        manager = get_manager()
        paper_id = str(request.get_json(force=True).get("paper_id", ""))
        row = manager.get_paper(paper_id)
        if row.get("FileState") != "Present":
            return jsonify({"error": "Only present PDFs can be opened."}), 400

        path = _validated_library_path(manager.root, row.get("Path", ""))
        if not path.exists() or not path.is_file():
            return jsonify({"error": f"PDF does not exist: {path}"}), 404
        _open_with_system(path)
        return jsonify({"ok": True, "path": str(path)})
    except Exception as exc:
        return mapped_error_response(exc)


@bp.post("/api/papers/show-in-folder")
def show_paper_in_folder():
    try:
        manager = get_manager()
        paper_id = str(request.get_json(force=True).get("paper_id", ""))
        row = manager.get_paper(paper_id)
        path = _validated_library_path(manager.root, row.get("Path", ""))
        folder = path if path.is_dir() else path.parent
        if not folder.exists() or not folder.is_dir():
            return jsonify({"error": f"Containing folder does not exist: {folder}"}), 404
        _open_with_system(folder)
        return jsonify({"ok": True, "path": str(folder)})
    except Exception as exc:
        return mapped_error_response(exc)


@bp.post("/api/topics/open")
def open_topic_folder():
    try:
        manager = get_manager()
        topic = str(request.get_json(force=True).get("topic", "")).strip()
        if not topic or "/" in topic or "\\" in topic:
            return jsonify({"error": "Enter a valid topic without path separators."}), 400
        folder = (manager.root / topic).resolve()
        _validated_library_path(manager.root, str(folder))
        if not folder.exists() or not folder.is_dir():
            return jsonify({"error": f"Topic folder does not exist: {folder}"}), 404
        _open_with_system(folder)
        return jsonify({"ok": True, "path": str(folder)})
    except Exception as exc:
        return mapped_error_response(exc)
