from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Callable

from reference_manager.constants import DEFAULT_COLUMNS
from reference_manager.library.identity import paper_id_for
from reference_manager.library.paths import manager_dir, report_path
from reference_manager.library.report import (
    LIBRARY_WRITE_LOCK,
    find_row,
    normalize_row,
    read_report,
    write_report_atomic,
)
from reference_manager.library.scanner import reconcile_library
from reference_manager.services.bibtex import best_bib_match, parse_bib_entry, split_bib_entries
from reference_manager.services.checkpoints import create_checkpoint, list_checkpoints, now_stamp
from reference_manager.services.csv_import import merge_imported_rows, read_uploaded_csv
from reference_manager.services.duplicates import find_duplicate_groups
from reference_manager.services.logging_service import log_operation
from reference_manager.services.pdf_metadata import extract_pdf_metadata
from reference_manager.utils.text import is_missing_title, normalize_title

ProgressCallback = Callable[[int, int, str], None]


class ReferenceManager:
    """Public, Flask-free interface to a local paper library.

    The standalone web app and the future unified project assistant can both
    depend on this class without importing UI or Flask code.
    """

    def __init__(self, library_root: str | Path):
        root = Path(library_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Library root does not exist: {root}")
        self.root = root

    def list_papers(self) -> list[dict[str, str]]:
        return read_report(self.root)

    def get_paper(self, paper_id: str) -> dict[str, str]:
        return find_row(self.list_papers(), paper_id)

    def save_papers(self, rows: list[dict[str, Any]]) -> int:
        current = self.list_papers()
        expected_ids = {row.get("PaperID", "") for row in current if row.get("PaperID")}
        write_report_atomic(self.root, rows, "save_metadata", expected_ids=expected_ids)
        return len(rows)

    def sync(
        self,
        *,
        detect_moves: bool = True,
        extract_titles: bool = True,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        rows, summary = reconcile_library(
            self.root,
            compute_hashes=detect_moves,
            progress=progress,
        )

        if extract_titles:
            targets = [
                row
                for row in rows
                if row.get("FileState") == "Present"
                and is_missing_title(row.get("Title", ""))
            ]
            for index, row in enumerate(targets, 1):
                if progress:
                    progress(index, len(targets), f"Extracting title: {row.get('Filename', '')}")
                try:
                    metadata = extract_pdf_metadata(Path(row["Path"]))
                    for key, value in metadata.items():
                        if value and (
                            not row.get(key)
                            or (key == "Title" and is_missing_title(row.get(key, "")))
                        ):
                            row[key] = value
                except Exception:
                    continue

        expected_ids = {row.get("PaperID", "") for row in self.list_papers() if row.get("PaperID")}
        write_report_atomic(self.root, rows, "sync_library", expected_ids=expected_ids)
        return {key: value for key, value in summary.items() if not key.endswith("_rows")}

    def extract_metadata(
        self,
        paper_id: str | None = None,
        *,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        with LIBRARY_WRITE_LOCK:
            rows = self.list_papers()
            if not rows:
                raise RuntimeError(
                    "The current paper_report.csv contains no records; extraction was cancelled without writing."
                )
            original_ids = {row.get("PaperID", "") for row in rows if row.get("PaperID")}
            targets = [find_row(rows, paper_id)] if paper_id else [
                row for row in rows if row.get("FileState") == "Present"
            ]
            updated = 0
            errors: list[dict[str, str]] = []
            for index, row in enumerate(targets, 1):
                if progress:
                    progress(index, len(targets), f"Reading {row.get('Filename', '')}")
                try:
                    path = Path(row["Path"])
                    if not path.exists():
                        errors.append({"paper_id": row.get("PaperID", ""), "error": f"File not found: {path}"})
                        continue
                    metadata = extract_pdf_metadata(path)
                    changed = False
                    for key, value in metadata.items():
                        if value and (
                            not row.get(key)
                            or (key == "Title" and is_missing_title(row.get(key, "")))
                        ):
                            row[key] = value
                            changed = True
                    if changed:
                        row["ModifiedDate"] = datetime.now().isoformat()
                        updated += 1
                except Exception as exc:
                    errors.append({
                        "paper_id": row.get("PaperID", ""),
                        "error": f"{type(exc).__name__}: {exc}",
                    })
            write_report_atomic(
                self.root,
                rows,
                "extract_pdf_metadata",
                expected_ids=original_ids,
            )
            return {
                "updated": updated,
                "processed": len(targets),
                "errors": errors[:50],
                "rows_preserved": len(rows),
            }

    def find_duplicates(self) -> list[list[dict[str, Any]]]:
        return find_duplicate_groups(self.list_papers())

    def import_csv(self, uploaded: BinaryIO, *, create_unmatched: bool = False) -> dict[str, Any]:
        incoming, recognized, unknown = read_uploaded_csv(uploaded)
        rows = self.list_papers()
        rows, summary = merge_imported_rows(rows, incoming, create_unmatched=create_unmatched)
        write_report_atomic(self.root, rows, "import_csv_transfer")
        return {
            "rows_imported": len(incoming),
            "recognized_columns": sorted(set(recognized)),
            "unknown_columns": unknown,
            **summary,
            "full_columns": DEFAULT_COLUMNS,
        }

    def import_bibtex_text(
        self,
        text: str,
        *,
        progress: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        entries = [
            entry
            for entry in (parse_bib_entry(raw) for raw in split_bib_entries(text))
            if entry
        ]
        rows = self.list_papers()
        matched = created = 0
        uncertain: list[dict[str, Any]] = []
        now = datetime.now().isoformat()

        for index, entry in enumerate(entries, 1):
            if progress:
                progress(index, len(entries), f"Matching BibTeX entry {index} of {len(entries)}")
            row, score = best_bib_match(entry, rows)
            title = entry.get("title", "") or "TITLE NOT FOUND"
            values = {
                "Title": title,
                "Authors": entry.get("author", ""),
                "Year": entry.get("year", ""),
                "Venue": entry.get("journal", "") or entry.get("booktitle", "") or entry.get("publisher", ""),
                "DOI": entry.get("doi", ""),
                "BibKey": entry.get("BibKey", ""),
                "Abstract": entry.get("abstract", ""),
                "Keywords": entry.get("keywords", ""),
                "ModifiedDate": now,
            }
            if row is not None and score >= 0.82:
                for key, value in values.items():
                    if value and (
                        not row.get(key)
                        or key in {"Authors", "Year", "Venue", "DOI", "BibKey", "Abstract", "Keywords"}
                    ):
                        row[key] = value
                if row.get("Status") in {"", "Needs Review", "OK"}:
                    row["Status"] = "Cited"
                matched += 1
            else:
                identity = entry.get("doi", "") or normalize_title(title)
                rows.append(normalize_row({
                    **values,
                    "Topic": "BibTeX Inbox",
                    "Status": "Cited",
                    "FileState": "Reference Only",
                    "PaperID": paper_id_for(identity, entry.get("BibKey", title)),
                }))
                created += 1
                if row is not None:
                    uncertain.append({
                        "bib_title": title,
                        "candidate": row.get("Title", ""),
                        "score": round(score, 3),
                    })

        write_report_atomic(self.root, rows, "import_bibtex")
        return {
            "matched": matched,
            "created": created,
            "uncertain": uncertain[:100],
            "entries": len(entries),
        }

    def move_paper(self, paper_id: str, destination_topic: str) -> dict[str, str]:
        destination_topic = destination_topic.strip()
        if not destination_topic or "/" in destination_topic or "\\" in destination_topic:
            raise ValueError("Enter a valid destination topic without path separators.")

        rows = self.list_papers()
        row = find_row(rows, paper_id)
        if row["FileState"] != "Present":
            raise ValueError("Only present PDFs can be moved.")
        src = Path(row["Path"]).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Source PDF does not exist: {src}")

        dst_dir = self.root / destination_topic
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if dst.exists() and dst.resolve() != src:
            raise FileExistsError(f"Destination already contains {dst.name}.")

        create_checkpoint(self.root, "move_paper", [src])
        shutil.move(str(src), str(dst))
        row.update({
            "Topic": destination_topic,
            "Path": str(dst.resolve()),
            "Filename": dst.name,
            "FileState": "Present",
        })
        write_report_atomic(self.root, rows, "move_paper_csv_update", checkpoint=False)
        log_operation(self.root, "move_paper", {"paper_id": paper_id, "from": str(src), "to": str(dst)})
        return row

    def archive_paper(self, paper_id: str) -> dict[str, str]:
        rows = self.list_papers()
        row = find_row(rows, paper_id)
        if row["FileState"] != "Present":
            raise ValueError("Only present PDFs can be archived.")
        src = Path(row["Path"]).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Source PDF does not exist: {src}")

        stamp = now_stamp()
        rel = src.relative_to(self.root)
        dst = manager_dir(self.root) / "deleted_pdfs" / stamp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        create_checkpoint(self.root, "archive_paper", [src])
        shutil.move(str(src), str(dst))
        row.update({
            "OriginalPath": str(src),
            "ArchivedAt": datetime.now().isoformat(),
            "Path": str(dst.resolve()),
            "FileState": "Deleted",
        })
        write_report_atomic(self.root, rows, "archive_paper_csv_update", checkpoint=False)
        log_operation(self.root, "archive_paper", {"paper_id": paper_id, "from": str(src), "archive": str(dst)})
        return row

    def restore_paper(self, paper_id: str, destination_topic: str = "") -> dict[str, str]:
        rows = self.list_papers()
        row = find_row(rows, paper_id)
        if row["FileState"] != "Deleted":
            raise ValueError("Only archived PDFs can be restored.")
        src = Path(row["Path"]).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Archived PDF does not exist: {src}")

        destination_topic = destination_topic.strip()
        if destination_topic:
            if "/" in destination_topic or "\\" in destination_topic:
                raise ValueError("Invalid destination topic.")
            dst = self.root / destination_topic / row["Filename"]
        elif row.get("OriginalPath"):
            dst = Path(row["OriginalPath"]).resolve()
            dst.relative_to(self.root)
        else:
            dst = self.root / row["Topic"] / row["Filename"]

        if dst.exists():
            raise FileExistsError(f"Restore destination already exists: {dst}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        create_checkpoint(self.root, "restore_paper", [src])
        shutil.move(str(src), str(dst))
        rel = dst.relative_to(self.root)
        topic = rel.parts[0] if len(rel.parts) > 1 else "Uncategorized"
        row.update({
            "Topic": topic,
            "Path": str(dst.resolve()),
            "Filename": dst.name,
            "FileState": "Present",
            "OriginalPath": "",
            "ArchivedAt": "",
        })
        write_report_atomic(self.root, rows, "restore_paper_csv_update", checkpoint=False)
        log_operation(self.root, "restore_paper", {"paper_id": paper_id, "from": str(src), "to": str(dst)})
        return row

    def history(self, limit: int = 100) -> list[dict[str, Any]]:
        path = manager_dir(self.root) / "logs" / "operations.jsonl"
        if not path.exists():
            return []
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return records[-limit:][::-1]

    def checkpoints(self) -> list[dict[str, Any]]:
        return list_checkpoints(self.root)

    def restore_latest_checkpoint(self) -> dict[str, Any]:
        with LIBRARY_WRITE_LOCK:
            base = manager_dir(self.root) / "checkpoints"
            candidates = sorted(
                [path for path in base.iterdir() if path.is_dir() and (path / "paper_report.csv").exists()],
                reverse=True,
            ) if base.exists() else []
            if not candidates:
                raise FileNotFoundError("No checkpoint containing paper_report.csv was found.")

            latest = candidates[0]
            source = latest / "paper_report.csv"
            emergency = base / f"before_restore_{now_stamp()}"
            emergency.mkdir(parents=True, exist_ok=True)
            current = report_path(self.root)
            if current.exists():
                shutil.copy2(current, emergency / "paper_report.csv")

            temp = self.root / "paper_report.restore.tmp"
            shutil.copy2(source, temp)
            with temp.open("r", encoding="utf-8-sig", newline="") as handle:
                restored_rows = [normalize_row(dict(row)) for row in csv.DictReader(handle)]
            if not restored_rows:
                temp.unlink(missing_ok=True)
                raise RuntimeError("The latest checkpoint report is empty; restore was cancelled.")
            os.replace(temp, current)
            log_operation(self.root, "restore_latest_report_checkpoint", {
                "checkpoint": latest.name,
                "rows_restored": len(restored_rows),
            })
            return {"checkpoint": latest.name, "rows_restored": len(restored_rows)}
