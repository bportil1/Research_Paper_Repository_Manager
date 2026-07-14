from __future__ import annotations

from flask import jsonify


def error_response(exc: Exception, status: int = 400):
    return jsonify({"error": f"{type(exc).__name__}: {exc}"}), status
