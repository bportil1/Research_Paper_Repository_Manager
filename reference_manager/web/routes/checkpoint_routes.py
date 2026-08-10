from __future__ import annotations

from flask import Blueprint, jsonify

from reference_manager.web.routes.common import error_response, get_manager, mapped_error_response

bp = Blueprint("checkpoint_api", __name__)


@bp.get("/api/history")
def history():
    try:
        return jsonify({"history": get_manager().history()})
    except Exception as exc:
        return error_response(exc)


@bp.get("/api/checkpoints")
def checkpoints():
    try:
        return jsonify({"checkpoints": get_manager().checkpoints()})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/checkpoints/restore-latest")
def restore_latest():
    try:
        result = get_manager().restore_latest_checkpoint()
        return jsonify({"ok": True, **result})
    except Exception as exc:
        return mapped_error_response(exc)
