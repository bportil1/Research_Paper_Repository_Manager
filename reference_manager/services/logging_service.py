from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from reference_manager.library.paths import ensure_manager_dirs, manager_dir

def log_operation(root: Path, operation: str, details: dict[str, Any]) -> None:
    ensure_manager_dirs(root)
    with (manager_dir(root)/"logs"/"operations.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"timestamp": datetime.now().isoformat(), "operation": operation, "details": details}) + "\n")
