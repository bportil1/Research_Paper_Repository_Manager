from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

from backend.constants import DEFAULT_COLUMNS
from backend.library.identity import paper_id_for
from backend.library.report import normalize_row
from backend.services.bibtex import best_bib_match
from backend.utils.text import is_missing_title, normalize_title

COLUMN_ALIASES = {
    "paperid": "PaperID", "paper id": "PaperID", "id": "PaperID",
    "topic": "Topic", "category": "Topic", "section": "Topic", "folder": "Topic",
    "title": "Title", "paper title": "Title",
    "filename": "Filename", "file": "Filename", "file name": "Filename",
    "path": "Path", "filepath": "Path", "file path": "Path",
    "status": "Status", "reading status": "Status",
    "notes": "Notes", "note": "Notes",
    "year": "Year", "authors": "Authors", "author": "Authors",
    "venue": "Venue", "journal": "Venue", "booktitle": "Venue",
    "doi": "DOI", "bibkey": "BibKey", "bib key": "BibKey", "citation key": "BibKey",
    "abstract": "Abstract", "keywords": "Keywords",
    "filestate": "FileState", "file state": "FileState",
    "sha256": "SHA256", "hash": "SHA256",
    "originalpath": "OriginalPath", "original path": "OriginalPath",
    "archivedat": "ArchivedAt", "archived at": "ArchivedAt",
    "addeddate": "AddedDate", "added date": "AddedDate",
    "modifieddate": "ModifiedDate", "modified date": "ModifiedDate",
}


def canonical_column(name: str) -> str | None:
    raw = str(name or "").replace("\ufeff", "").strip()
    if raw in DEFAULT_COLUMNS:
        return raw
    key = re.sub(r"\s+", " ", raw.lower().replace("-", " ").replace("_", " ")).strip()
    return COLUMN_ALIASES.get(key) or COLUMN_ALIASES.get(key.replace(" ", ""))


def read_uploaded_csv(uploaded):
    text = uploaded.read().decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    rows = list(csv.reader(text.splitlines(), dialect))
    while rows and not any(str(value).strip() for value in rows[0]):
        rows.pop(0)
    if not rows:
        return [], [], []

    headers = [str(value or "").strip() for value in rows[0]]
    mapped = [canonical_column(header) for header in headers]
    recognized = [header for header in mapped if header]
    unknown = [headers[index] for index, value in enumerate(mapped) if not value and headers[index]]
    if not recognized:
        raise ValueError("The CSV does not contain any recognized paper-manager columns.")

    imported = []
    for values in rows[1:]:
        if not any(str(value).strip() for value in values):
            continue
        row = {}
        extras = {}
        for index, value in enumerate(values):
            value = str(value or "").strip()
            if index < len(mapped) and mapped[index]:
                if value:
                    row[mapped[index]] = value
            elif index < len(headers) and headers[index] and value:
                extras[headers[index]] = value
            elif value:
                extras[f"ExtraColumn{index + 1}"] = value
        if extras:
            row["Notes"] = (
                row.get("Notes", "")
                + " | Imported extra fields: "
                + json.dumps(extras, ensure_ascii=False)
            ).strip(" |")
        imported.append(row)
    return imported, recognized, unknown


def merge_imported_rows(existing, incoming, create_unmatched=False):
    protected = {
        "PaperID", "Topic", "Filename", "Path", "FileState",
        "SHA256", "OriginalPath", "ArchivedAt",
    }
    transferable = [column for column in DEFAULT_COLUMNS if column not in protected]

    indexes = {key: {} for key in ("PaperID", "SHA256", "DOI", "Path", "Filename", "Title")}
    for row in existing:
        values = {
            "PaperID": row.get("PaperID", ""),
            "SHA256": row.get("SHA256", "").lower(),
            "DOI": row.get("DOI", "").lower().strip(),
            "Path": str(Path(row["Path"]).expanduser()) if row.get("Path") else "",
            "Filename": row.get("Filename", "").lower().strip(),
            "Title": normalize_title(row.get("Title", "")) if not is_missing_title(row.get("Title", "")) else "",
        }
        for kind, value in values.items():
            if value:
                indexes[kind][value] = row

    matched = created = updated_fields = unmatched = 0
    for raw in incoming:
        incoming_row = {column: str(raw.get(column, "") or "").strip() for column in DEFAULT_COLUMNS}
        target = None
        for kind, value in (
            ("PaperID", incoming_row.get("PaperID", "")),
            ("SHA256", incoming_row.get("SHA256", "").lower()),
            ("DOI", incoming_row.get("DOI", "").lower().strip()),
            ("Path", str(Path(incoming_row["Path"]).expanduser()) if incoming_row.get("Path") else ""),
            ("Filename", incoming_row.get("Filename", "").lower().strip()),
            ("Title", normalize_title(incoming_row.get("Title", "")) if not is_missing_title(incoming_row.get("Title", "")) else ""),
        ):
            if value and value in indexes[kind]:
                target = indexes[kind][value]
                break

        if target is None and incoming_row.get("Title") and not is_missing_title(incoming_row["Title"]):
            candidate, score = best_bib_match(
                {"title": incoming_row["Title"], "doi": incoming_row.get("DOI", "")},
                existing,
            )
            if candidate is not None and score >= 0.94:
                target = candidate

        if target is not None:
            matched += 1
            for column in transferable:
                value = incoming_row.get(column, "")
                if not value or (column == "Title" and is_missing_title(value)):
                    continue
                if target.get(column) != value:
                    target[column] = value
                    updated_fields += 1
            target["ModifiedDate"] = datetime.now().isoformat()
        elif create_unmatched:
            new_row = normalize_row(incoming_row)
            new_row.update({
                "Topic": "CSV Import Inbox",
                "Path": "",
                "FileState": "Reference Only",
                "SHA256": "",
                "OriginalPath": "",
                "ArchivedAt": "",
            })
            identity = (
                new_row.get("DOI")
                or normalize_title(new_row.get("Title", ""))
                or new_row.get("Filename")
                or datetime.now().isoformat()
            )
            new_row["PaperID"] = new_row.get("PaperID") or paper_id_for(identity, new_row.get("Filename") or identity)
            existing.append(new_row)
            created += 1
        else:
            unmatched += 1

    return existing, {
        "matched": matched,
        "created": created,
        "unmatched": unmatched,
        "updated_fields": updated_fields,
    }
