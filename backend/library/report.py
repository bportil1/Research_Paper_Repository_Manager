from __future__ import annotations

import csv
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from backend.constants import DEFAULT_COLUMNS
from backend.library.identity import ensure_unique_paper_ids
from backend.library.paths import ensure_manager_dirs, report_path
from backend.models.paper import Paper

LIBRARY_WRITE_LOCK = threading.RLock()


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    return Paper.from_mapping(row).to_dict()


def read_report(root: Path) -> list[dict[str, str]]:
    path = report_path(root)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [normalize_row(dict(row)) for row in csv.DictReader(stream)]


def write_report_atomic(root: Path, rows: list[dict[str, Any]], operation: str, checkpoint: bool = True, allow_empty: bool = False, expected_ids: set[str] | None = None) -> None:
    # Imports are local to avoid a report/checkpoint circular import.
    from backend.services.checkpoints import create_checkpoint
    from backend.services.logging_service import log_operation

    with LIBRARY_WRITE_LOCK:
        ensure_manager_dirs(root)
        current_rows = read_report(root)
        normalized, repairs = ensure_unique_paper_ids(rows)
        if current_rows and not normalized and not allow_empty:
            raise RuntimeError(f"Refusing to replace a nonempty report ({len(current_rows)} rows) with an empty report.")
        ids = [row["PaperID"] for row in normalized if row.get("PaperID")]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Internal PaperID repair failed to produce unique IDs.")
        if expected_ids is not None:
            missing = expected_ids - set(ids)
            if missing:
                raise RuntimeError(f"Refusing report write because {len(missing)} existing records would be lost.")
        checkpoint_path = create_checkpoint(root, operation, []) if checkpoint else None
        target = report_path(root)
        fd, temp_name = tempfile.mkstemp(prefix="paper_report_", suffix=".tmp", dir=str(root))
        os.close(fd)
        temp = Path(temp_name)
        try:
            with temp.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=DEFAULT_COLUMNS, quoting=csv.QUOTE_ALL, escapechar="\\", doublequote=True)
                writer.writeheader(); writer.writerows(normalized)
            with temp.open("r", encoding="utf-8-sig", newline="") as stream:
                checked = [normalize_row(dict(row)) for row in csv.DictReader(stream)]
            if len(checked) != len(normalized):
                raise RuntimeError(f"CSV validation failed: wrote {len(normalized)} rows but read back {len(checked)}.")
            checked_ids = [row["PaperID"] for row in checked if row.get("PaperID")]
            if len(checked_ids) != len(set(checked_ids)):
                raise RuntimeError("CSV validation failed: duplicate PaperID values after serialization.")
            os.replace(temp, target)
            log_operation(root, operation, {"rows_before": len(current_rows), "rows_written": len(normalized), "paper_ids_repaired": len(repairs), "checkpoint": str(checkpoint_path) if checkpoint_path else ""})
        finally:
            temp.unlink(missing_ok=True)


def find_row(rows: list[dict[str, str]], paper_id: str) -> dict[str, str]:
    for row in rows:
        if row.get("PaperID") == paper_id:
            return row
    raise KeyError(f"Paper not found: {paper_id}")
