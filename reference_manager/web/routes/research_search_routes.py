from __future__ import annotations

import socket
import subprocess
import sys
import time
from pathlib import Path

from flask import Blueprint, jsonify

bp = Blueprint("research_search", __name__)
SEARCH_HOST = "127.0.0.1"
SEARCH_PORT = 8770
SEARCH_URL = f"http://{SEARCH_HOST}:{SEARCH_PORT}/research-search"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _search_module_root() -> Path:
    return _project_root() / "modules" / "paper_searcher"


def _port_open(host: str, port: int, timeout: float = 0.2) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@bp.post("/api/research-search/launch")
def launch_research_search():
    if _port_open(SEARCH_HOST, SEARCH_PORT):
        return jsonify({"ok": True, "url": SEARCH_URL, "already_running": True})

    module_root = _search_module_root()
    run_file = module_root / "run.py"
    if not run_file.exists():
        return jsonify({
            "error": (
                "Research Search module is not installed. Expected nested module at "
                f"{module_root}. Run git submodule update --init --recursive after the "
                "paper_searcher repository is added as a submodule."
            )
        }), 404

    subprocess.Popen(
        [sys.executable, str(run_file)],
        cwd=str(module_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    # Give the standalone service a short startup window so the browser does
    # not race the new process and land on a connection-refused page.
    for _ in range(30):
        if _port_open(SEARCH_HOST, SEARCH_PORT):
            return jsonify({"ok": True, "url": SEARCH_URL, "already_running": False})
        time.sleep(0.1)

    return jsonify({
        "error": (
            "Research Search was started but did not become reachable on "
            f"{SEARCH_HOST}:{SEARCH_PORT}. Run modules/paper_searcher/run.py "
            "directly to see its startup error."
        )
    }), 500
