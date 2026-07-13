from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = APP_DIR / "config.json"

def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {"library_root": ""}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def save_config(config: dict[str, Any]) -> None:
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2), encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)

def get_library_root() -> Path:
    raw = str(load_config().get("library_root", "")).strip()
    if not raw:
        raise RuntimeError("Library root has not been configured.")
    root = Path(raw).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Configured library root does not exist: {root}")
    return root
