from __future__ import annotations

from datetime import datetime

from flask import Blueprint, jsonify, request

from backend.api.common import error_response
from backend.config import get_library_root
from backend.constants import DEFAULT_COLUMNS
from backend.jobs.manager import create_job, run_job, update_job
from backend.library.identity import paper_id_for
from backend.library.report import normalize_row, read_report, write_report_atomic
from backend.services.bibtex import best_bib_match, parse_bib_entry, split_bib_entries
from backend.services.csv_import import merge_imported_rows, read_uploaded_csv
from backend.utils.text import normalize_title

bp = Blueprint("import_api", __name__)


@bp.post("/api/csv/import")
def import_csv():
    try:
        root = get_library_root()
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "Choose a CSV file."}), 400
        create_unmatched = str(request.form.get("create_unmatched", "false")).lower() == "true"
        incoming, recognized, unknown = read_uploaded_csv(uploaded)
        job_id = create_job("csv_import", "Preparing CSV metadata transfer")

        def task():
            update_job(job_id, current=0, total=len(incoming), message=f"Matching {len(incoming)} imported rows")
            rows = read_report(root)
            rows, summary = merge_imported_rows(rows, incoming, create_unmatched=create_unmatched)
            update_job(job_id, current=len(incoming), total=len(incoming), message="Writing full-schema report")
            write_report_atomic(root, rows, "import_csv_transfer")
            return {
                "rows_imported": len(incoming),
                "recognized_columns": sorted(set(recognized)),
                "unknown_columns": unknown,
                **summary,
                "full_columns": DEFAULT_COLUMNS,
            }

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)


@bp.post("/api/bib/import")
def import_bibtex():
    try:
        root = get_library_root()
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "Choose a .bib file."}), 400
        text = uploaded.read().decode("utf-8", errors="replace")
        entries = [entry for entry in (parse_bib_entry(raw) for raw in split_bib_entries(text)) if entry]
        job_id = create_job("bib_import", f"Parsed {len(entries)} BibTeX entries")

        def task():
            rows = read_report(root)
            matched = created = 0
            uncertain = []
            now = datetime.now().isoformat()
            for index, entry in enumerate(entries, 1):
                update_job(job_id, current=index, total=len(entries), message=f"Matching BibTeX entry {index} of {len(entries)}")
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
                        if value and (not row.get(key) or key in {"Authors", "Year", "Venue", "DOI", "BibKey", "Abstract", "Keywords"}):
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
            write_report_atomic(root, rows, "import_bibtex")
            return {
                "matched": matched,
                "created": created,
                "uncertain": uncertain[:100],
                "entries": len(entries),
            }

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as exc:
        return error_response(exc)
