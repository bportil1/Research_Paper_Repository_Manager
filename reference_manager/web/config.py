from __future__ import annotations

import json
import os
import tempfile
from threading import RLock
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = APP_DIR / "config.json"
_CONFIG_LOCK = RLock()


def _config_path() -> Path:
    # The legacy host can still replace CONFIG_PATH; independent child processes
    # select a per-instance path via their trusted launch environment.
    override = os.environ.get("REFERENCE_MANAGER_CONFIG_PATH", "").strip()
    return Path(override).expanduser().resolve() if override else CONFIG_PATH


def load_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {"library_root": ""}
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("Reference Manager configuration must be a JSON object")
    return result


def save_config(config: dict[str, Any]) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # A unique temp file prevents two writers to a legacy shared config path
    # from colliding on the same .tmp filename; PAH children have unique paths.
    with _CONFIG_LOCK:
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", dir=str(path.parent),
                                             prefix=".reference-config-", suffix=".tmp",
                                             encoding="utf-8", delete=False) as stream:
                tmp = Path(stream.name)
                json.dump(config, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, path)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)


def get_library_root() -> Path:
    raw = str(load_config().get("library_root", "")).strip()
    if not raw:
        raise RuntimeError("Library root has not been configured.")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Configured library root does not exist: {root}")
    return root
