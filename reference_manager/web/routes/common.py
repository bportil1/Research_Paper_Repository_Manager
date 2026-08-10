from __future__ import annotations

from flask import jsonify

from reference_manager import ReferenceManager
from reference_manager.web.config import get_library_root


def get_manager() -> ReferenceManager:
    return ReferenceManager(get_library_root())


def error_response(exc: Exception, status: int = 400):
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), status


def mapped_error_response(exc: Exception):
    if isinstance(exc, KeyError):
        return error_response(exc, 404)
    if isinstance(exc, FileNotFoundError):
        return error_response(exc, 404)
    if isinstance(exc, FileExistsError):
        return error_response(exc, 409)
    return error_response(exc, 400)
