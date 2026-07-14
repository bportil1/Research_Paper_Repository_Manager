from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from backend.library.identity import paper_id_for, sha256_file
from backend.library.paths import filesystem_pdfs
from backend.library.report import normalize_row, read_report


def reconcile_library(root: Path, compute_hashes: bool = False, progress: Callable[[int, int, str], None] | None = None) -> tuple[list[dict[str, str]], dict[str, Any]]:
    old_rows = read_report(root)
    active = [row for row in old_rows if row.get("FileState") != "Deleted"]
    deleted = [row for row in old_rows if row.get("FileState") == "Deleted"]
    by_path = {row["Path"]: row for row in active if row.get("Path")}
    by_hash = {row["SHA256"]: row for row in active if row.get("SHA256")}
    pdfs = filesystem_pdfs(root)
    result, new_rows, moved_rows = [], [], []
    matched_ids: set[str] = set()
    for index, pdf in enumerate(pdfs, 1):
        if progress: progress(index - 1, len(pdfs), f"Scanning {pdf.name}")
        resolved = str(pdf.resolve())
        relative = pdf.relative_to(root)
        topic = relative.parts[0] if len(relative.parts) > 1 else "Uncategorized"
        old = by_path.get(resolved)
        digest = old.get("SHA256", "") if old else ""
        if old is None and compute_hashes:
            digest = sha256_file(pdf)
            candidate = by_hash.get(digest)
            if candidate and candidate.get("PaperID") not in matched_ids:
                old = candidate
                moved_rows.append({"PaperID": candidate.get("PaperID", ""), "Title": candidate.get("Title", ""), "from": candidate.get("Path", ""), "to": resolved})
        row = normalize_row({**(old or {}), "PaperID": (old or {}).get("PaperID", "") or paper_id_for(digest, resolved), "Topic": topic, "Filename": pdf.name, "Path": resolved, "FileState": "Present", "SHA256": digest, "OriginalPath": "", "ArchivedAt": ""})
        result.append(row); matched_ids.add(row["PaperID"])
        if old is None: new_rows.append(row)
    missing_rows = []
    for old in active:
        if old.get("PaperID") not in matched_ids:
            missing = normalize_row(old); missing["FileState"] = "Missing"
            result.append(missing); missing_rows.append(missing)
    result.extend(deleted)
    if progress: progress(len(pdfs), len(pdfs), "Directory scan complete")
    return result, {"new": len(new_rows), "missing": len(missing_rows), "moved_or_renamed": len(moved_rows), "total_after_sync": len(result), "new_rows": new_rows, "missing_rows": missing_rows, "moved_rows": moved_rows}
