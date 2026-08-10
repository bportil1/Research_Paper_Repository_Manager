from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from reference_manager.web.routes.common import error_response
from reference_manager.web.config import load_config, save_config
from reference_manager.library.paths import ensure_manager_dirs

bp = Blueprint("config_api", __name__)


@bp.get("/api/config")
def get_config():
    return jsonify(load_config())


@bp.post("/api/config")
def set_config():
    try:
        data = request.get_json(force=True)
        root = Path(str(data.get("library_root", "")).strip()).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            return jsonify({"error": f"Directory does not exist: {root}"}), 400
        save_config({"library_root": str(root)})
        ensure_manager_dirs(root)
        return jsonify({"ok": True, "library_root": str(root)})
    except Exception as exc:
        return error_response(exc)
