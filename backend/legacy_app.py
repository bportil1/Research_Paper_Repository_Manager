from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_from_directory

APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "config.json"

DEFAULT_COLUMNS = [
    "PaperID", "Topic", "Title", "Filename", "Path", "Status", "Notes",
    "Year", "Authors", "Venue", "DOI", "BibKey", "Abstract", "Keywords",
    "FileState", "SHA256", "OriginalPath", "ArchivedAt", "AddedDate", "ModifiedDate",
]
IGNORED_DIRS = {".paper_manager", ".git", "__pycache__"}
ALLOWED_STATUSES = {"OK", "Needs Review", "Priority", "Read", "Ignore", "Cited"}

app = Flask(__name__, static_folder="static")

JOB_EXECUTOR = ThreadPoolExecutor(max_workers=2)
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()
LIBRARY_WRITE_LOCK = threading.RLock()


def create_job(kind: str, message: str = "Queued") -> str:
    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "queued",
            "message": message,
            "current": 0,
            "total": 0,
            "result": None,
            "error": "",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
    return job_id


def update_job(job_id: str, **changes: Any) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.update(changes)
        job["updated_at"] = datetime.now().isoformat()


def run_job(job_id: str, fn) -> None:
    def wrapped():
        update_job(job_id, status="running")
        try:
            result = fn()
            update_job(job_id, status="done", message="Complete", result=result)
        except Exception as exc:
            details = traceback.format_exc()
            update_job(
                job_id,
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                error_details=details,
                message="Failed — open details for the exact error",
            )
    JOB_EXECUTOR.submit(wrapped)


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")


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


def manager_dir(root: Path) -> Path:
    return root / ".paper_manager"


def ensure_manager_dirs(root: Path) -> None:
    base = manager_dir(root)
    for child in ("checkpoints", "deleted_pdfs", "logs"):
        (base / child).mkdir(parents=True, exist_ok=True)


def report_path(root: Path) -> Path:
    return root / "paper_report.csv"



def sanitize_text(value: Any) -> str:
    """Remove characters that cannot safely round-trip through CSV."""
    text = str(value or "")
    # NUL is rejected by Python's csv reader. Remove other disallowed
    # C0 control characters while preserving tab/newline/carriage return.
    text = text.replace("\x00", " ")
    text = "".join(
        ch if ch in "\t\n\r" or ord(ch) >= 32 else " "
        for ch in text
    )
    # Normalize repeated whitespace without destroying readable content.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_row(row: dict[str, Any]) -> dict[str, str]:
    clean = {col: sanitize_text(row.get(col, "")) for col in DEFAULT_COLUMNS}
    clean["Topic"] = clean["Topic"] or "Uncategorized"
    clean["Title"] = clean["Title"] or "TITLE NOT FOUND"
    clean["Status"] = clean["Status"] if clean["Status"] in ALLOWED_STATUSES else "Needs Review"
    clean["FileState"] = clean["FileState"] or "Present"
    clean["AddedDate"] = clean["AddedDate"] or datetime.now().date().isoformat()
    clean["ModifiedDate"] = clean["ModifiedDate"] or datetime.now().isoformat()
    return clean


def read_report(root: Path) -> list[dict[str, str]]:
    path = report_path(root)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [normalize_row(dict(row)) for row in csv.DictReader(f)]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def paper_id_for(digest: str, filename: str) -> str:
    identity = digest or filename
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def filesystem_pdfs(root: Path) -> list[Path]:
    return [
        p for p in sorted(root.rglob("*.pdf"))
        if not any(part in IGNORED_DIRS for part in p.relative_to(root).parts)
    ]


def ensure_unique_paper_ids(rows: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return normalized rows with unique, stable PaperID values.

    Older reports and duplicate PDF copies can legitimately contain the same
    PaperID. The first occurrence keeps its ID. Later occurrences receive a
    deterministic ID derived from their identity and path. No rows are removed
    or merged.
    """
    normalized = [normalize_row(row) for row in rows]
    # Final defensive pass: prevent embedded NUL/control bytes from reaching CSV.
    normalized = [
        {col: sanitize_text(row.get(col, "")) for col in DEFAULT_COLUMNS}
        for row in normalized
    ]
    used: set[str] = set()
    repairs: list[dict[str, str]] = []

    for index, row in enumerate(normalized):
        original = str(row.get("PaperID", "") or "").strip()
        candidate = original

        if not candidate or candidate in used:
            identity_parts = [
                original,
                row.get("SHA256", ""),
                row.get("Path", ""),
                row.get("Filename", ""),
                row.get("Title", ""),
                str(index),
            ]
            seed = "|".join(identity_parts)
            salt = 0
            while True:
                candidate = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()[:16]
                if candidate not in used:
                    break
                salt += 1

            row["PaperID"] = candidate
            repairs.append({
                "old_id": original,
                "new_id": candidate,
                "path": row.get("Path", ""),
                "title": row.get("Title", ""),
            })

        used.add(candidate)

    return normalized, repairs


def reconcile_library(
    root: Path,
    compute_hashes: bool = False,
    progress=None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Reconcile the directory with the report.

    Existing files matched by exact path are fast and are not re-hashed. New paths
    are hashed only when move/rename detection is requested. This avoids hashing the
    entire library on every synchronization.
    """
    old_rows = read_report(root)
    active_old = [r for r in old_rows if r.get("FileState") != "Deleted"]
    deleted_old = [r for r in old_rows if r.get("FileState") == "Deleted"]
    old_by_path = {r["Path"]: r for r in active_old if r.get("Path")}
    old_by_hash = {r["SHA256"]: r for r in active_old if r.get("SHA256")}

    pdfs = filesystem_pdfs(root)
    result: list[dict[str, str]] = []
    matched_ids: set[str] = set()
    new_rows: list[dict[str, str]] = []
    moved_rows: list[dict[str, str]] = []

    for index, pdf in enumerate(pdfs, 1):
        if progress:
            progress(index - 1, len(pdfs), f"Scanning {pdf.name}")
        resolved = str(pdf.resolve())
        rel = pdf.relative_to(root)
        topic = rel.parts[0] if len(rel.parts) > 1 else "Uncategorized"
        old = old_by_path.get(resolved)
        digest = old.get("SHA256", "") if old else ""

        # Hash only new paths when rename detection is requested. Existing paths
        # retain their stored hash and do not block normal synchronization.
        if old is None and compute_hashes:
            digest = sha256_file(pdf)
            candidate = old_by_hash.get(digest)
            if candidate and candidate.get("PaperID") not in matched_ids:
                old = candidate
                moved_rows.append({
                    "PaperID": candidate.get("PaperID", ""),
                    "Title": candidate.get("Title", ""),
                    "from": candidate.get("Path", ""),
                    "to": resolved,
                })

        row = normalize_row({
            **(old or {}),
            "PaperID": (old or {}).get("PaperID", "") or paper_id_for(digest, resolved),
            "Topic": topic,
            "Filename": pdf.name,
            "Path": resolved,
            "FileState": "Present",
            "SHA256": digest,
            "OriginalPath": "",
            "ArchivedAt": "",
        })
        result.append(row)
        matched_ids.add(row["PaperID"])
        if old is None:
            new_rows.append(row)

    missing_rows: list[dict[str, str]] = []
    for old in active_old:
        if old.get("PaperID") not in matched_ids:
            missing = normalize_row(old)
            missing["FileState"] = "Missing"
            result.append(missing)
            missing_rows.append(missing)

    result.extend(deleted_old)
    if progress:
        progress(len(pdfs), len(pdfs), "Directory scan complete")
    summary = {
        "new": len(new_rows),
        "missing": len(missing_rows),
        "moved_or_renamed": len(moved_rows),
        "total_after_sync": len(result),
        "new_rows": new_rows,
        "missing_rows": missing_rows,
        "moved_rows": moved_rows,
    }
    return result, summary

def enrich_missing_pdf_metadata(rows: list[dict[str, str]], only_new_ids: set[str] | None = None) -> dict[str, int]:
    updated = errors = 0
    for row in rows:
        if row.get("FileState") != "Present":
            continue
        if only_new_ids is not None and row.get("PaperID") not in only_new_ids and not is_missing_title(row.get("Title", "")):
            continue
        if not is_missing_title(row.get("Title", "")) and row.get("Authors") and row.get("Keywords"):
            continue
        try:
            path = Path(row.get("Path", ""))
            if not path.exists():
                continue
            md = extract_pdf_metadata(path)
            changed = False
            for key, val in md.items():
                if val and (not row.get(key) or (key == "Title" and is_missing_title(row.get(key, "")))):
                    row[key] = val
                    changed = True
            if changed:
                row["ModifiedDate"] = datetime.now().isoformat()
                updated += 1
        except Exception:
            errors += 1
    return {"metadata_updated": updated, "metadata_errors": errors}


def create_checkpoint(root: Path, operation: str, include_files: list[Path]) -> Path:
    ensure_manager_dirs(root)
    cp = manager_dir(root) / "checkpoints" / now_stamp()
    cp.mkdir(parents=True, exist_ok=True)

    current_report = report_path(root)
    if current_report.exists():
        shutil.copy2(current_report, cp / "paper_report.csv")

    manifest_rows, _ = reconcile_library(root, compute_hashes=False)
    with (cp / "library_manifest.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS, quoting=csv.QUOTE_ALL, escapechar="\\", doublequote=True)
        writer.writeheader()
        writer.writerows(manifest_rows)

    copied = []
    for src in include_files:
        if src.exists() and src.is_file():
            try:
                rel = src.resolve().relative_to(root.resolve())
            except ValueError:
                rel = Path(src.name)
            dst = cp / "files" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied.append(str(rel))

    (cp / "operation.json").write_text(json.dumps({
        "created_at": datetime.now().isoformat(),
        "operation": operation,
        "copied_files": copied,
    }, indent=2), encoding="utf-8")
    return cp


def log_operation(root: Path, operation: str, details: dict[str, Any]) -> None:
    ensure_manager_dirs(root)
    path = manager_dir(root) / "logs" / "operations.jsonl"
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "operation": operation,
            "details": details,
        }) + "\n")


def write_report_atomic(
    root: Path,
    rows: list[dict[str, Any]],
    operation: str,
    checkpoint: bool = True,
    allow_empty: bool = False,
    expected_ids: set[str] | None = None,
) -> None:
    """Safely replace paper_report.csv with validation and automatic rollback.

    Empty writes are rejected when the current report is nonempty. When
    expected_ids is supplied, every existing record must still be present.
    """
    with LIBRARY_WRITE_LOCK:
        ensure_manager_dirs(root)
        current_rows = read_report(root)
        normalized, id_repairs = ensure_unique_paper_ids(rows)

        if current_rows and not normalized and not allow_empty:
            raise RuntimeError(
                f"Refusing to replace a nonempty report ({len(current_rows)} rows) with an empty report."
            )

        ids = [row.get("PaperID", "") for row in normalized if row.get("PaperID", "")]
        if len(ids) != len(set(ids)):
            raise RuntimeError("Internal PaperID repair failed to produce unique IDs.")

        if expected_ids is not None:
            output_ids = set(ids)
            missing_ids = expected_ids - output_ids
            if missing_ids:
                raise RuntimeError(
                    f"Refusing report write because {len(missing_ids)} existing records would be lost."
                )

        checkpoint_path = None
        if checkpoint:
            checkpoint_path = create_checkpoint(root, operation=operation, include_files=[])

        target = report_path(root)
        fd, tmp_name = tempfile.mkstemp(prefix="paper_report_", suffix=".tmp", dir=str(root))
        os.close(fd)
        tmp_path = Path(tmp_name)

        try:
            with tmp_path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=DEFAULT_COLUMNS, quoting=csv.QUOTE_ALL, escapechar="\\", doublequote=True)
                writer.writeheader()
                writer.writerows(normalized)

            with tmp_path.open("r", encoding="utf-8-sig", newline="") as f:
                check_rows = [normalize_row(dict(row)) for row in csv.DictReader(f)]

            if len(check_rows) != len(normalized):
                raise RuntimeError(
                    f"CSV validation failed: wrote {len(normalized)} rows but read back {len(check_rows)}."
                )

            check_ids = [row.get("PaperID", "") for row in check_rows if row.get("PaperID", "")]
            if len(check_ids) != len(set(check_ids)):
                raise RuntimeError("CSV validation failed: duplicate PaperID values after serialization.")

            os.replace(tmp_path, target)
            log_operation(root, operation, {
                "rows_before": len(current_rows),
                "rows_written": len(normalized),
                "paper_ids_repaired": len(id_repairs),
                "paper_id_repairs": id_repairs[:100],
                "checkpoint": str(checkpoint_path) if checkpoint_path else "",
            })
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise
        finally:
            tmp_path.unlink(missing_ok=True)


def find_row(rows: list[dict[str, str]], paper_id: str) -> dict[str, str]:
    for row in rows:
        if row.get("PaperID") == paper_id:
            return row
    raise KeyError(f"Paper not found: {paper_id}")



def normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())


def split_bib_entries(text: str) -> list[str]:
    entries = []
    i = 0
    while True:
        at = text.find("@", i)
        if at < 0:
            break
        brace = text.find("{", at)
        if brace < 0:
            break
        depth = 0
        for j in range(brace, len(text)):
            if text[j] == "{": depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    entries.append(text[at:j+1]); i = j + 1; break
        else:
            break
    return entries


def parse_bib_entry(entry: str) -> dict[str, str] | None:
    head = re.match(r"@\s*(\w+)\s*\{\s*([^,\s]+)\s*,", entry, re.S)
    if not head:
        return None

    result = {"EntryType": head.group(1), "BibKey": head.group(2)}
    body = entry[head.end():]
    if body.rstrip().endswith("}"):
        body = body.rstrip()[:-1]

    i = 0
    while i < len(body):
        while i < len(body) and (body[i].isspace() or body[i] == ","):
            i += 1
        field_start = i
        while i < len(body) and (body[i].isalnum() or body[i] in "_-"):
            i += 1
        field = body[field_start:i].lower().strip()
        if not field:
            i += 1
            continue

        while i < len(body) and body[i].isspace():
            i += 1
        if i >= len(body) or body[i] != "=":
            while i < len(body) and body[i] not in ",\n":
                i += 1
            continue
        i += 1
        while i < len(body) and body[i].isspace():
            i += 1

        value = ""
        if i < len(body) and body[i] == "{":
            depth = 1
            i += 1
            chars = []
            while i < len(body) and depth:
                c = body[i]
                if c == "{":
                    depth += 1
                    if depth > 1:
                        chars.append(c)
                elif c == "}":
                    depth -= 1
                    if depth > 0:
                        chars.append(c)
                else:
                    chars.append(c)
                i += 1
            value = "".join(chars)
        elif i < len(body) and body[i] == '"':
            i += 1
            chars = []
            escaped = False
            while i < len(body):
                c = body[i]
                if c == '"' and not escaped:
                    i += 1
                    break
                chars.append(c)
                escaped = c == "\\" and not escaped
                if c != "\\":
                    escaped = False
                i += 1
            value = "".join(chars)
        else:
            start_value = i
            while i < len(body) and body[i] not in ",\n":
                i += 1
            value = body[start_value:i]

        result[field] = re.sub(r"\s+", " ", value.replace("{", "").replace("}", "")).strip()

    return result


def title_similarity(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, normalize_title(a), normalize_title(b)).ratio()


def best_bib_match(entry: dict[str, str], rows: list[dict[str, str]]) -> tuple[dict[str, str] | None, float]:
    doi = entry.get("doi", "").lower().strip()
    if doi:
        for row in rows:
            if row.get("DOI", "").lower().strip() == doi:
                return row, 1.0
    title = entry.get("title", "")
    if not title: return None, 0.0
    best, score = None, 0.0
    for row in rows:
        s = title_similarity(title, row.get("Title", ""))
        if s > score: best, score = row, s
    return best, score


def is_missing_title(value: str) -> bool:
    normalized = normalize_title(value)
    return not normalized or normalized in {"title not found", "error reading pdf"} or normalized.startswith("error reading pdf")


def extract_pdf_metadata(path: Path) -> dict[str, str]:
    import fitz

    doc = fitz.open(path)
    meta = doc.metadata or {}
    metadata_title = str(meta.get("title", "") or "").strip()
    authors = str(meta.get("author", "") or "").strip()
    keywords = str(meta.get("keywords", "") or "").strip()
    subject = str(meta.get("subject", "") or "").strip()

    title = metadata_title if not is_missing_title(metadata_title) else ""
    if len(doc):
        page = doc[0]
        page_height = float(page.rect.height or 792)
        blocks = page.get_text("dict").get("blocks", [])
        candidates: list[tuple[float, float, str]] = []
        for block in blocks:
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = " ".join(str(span.get("text", "")).strip() for span in spans).strip()
                text = re.sub(r"\s+", " ", text)
                if not text or len(text) < 6:
                    continue
                lowered = text.lower().strip(" :.-")
                if lowered in {"abstract", "introduction", "keywords", "contents"}:
                    continue
                if lowered.startswith(("arxiv:", "doi:", "http://", "https://")):
                    continue
                sizes = [float(span.get("size", 0) or 0) for span in spans]
                ys = [float((span.get("bbox") or [0, page_height, 0, page_height])[1]) for span in spans]
                size = max(sizes or [0])
                y = min(ys or [page_height])
                if y <= page_height * 0.48 and size >= 8:
                    candidates.append((size, y, text))

        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[1]))
            max_size = candidates[0][0]
            likely = [item for item in candidates if item[0] >= max_size * 0.82]
            likely.sort(key=lambda item: item[1])
            parts: list[str] = []
            for _, _, text in likely:
                if text not in parts:
                    parts.append(text)
                if len(" ".join(parts)) >= 350:
                    break
            inferred = " ".join(parts).strip()[:500]
            if inferred and not is_missing_title(inferred):
                title = inferred

        if not title:
            lines = [re.sub(r"\s+", " ", line).strip() for line in page.get_text("text").splitlines()]
            lines = [line for line in lines if len(line) >= 8 and line.lower() not in {"abstract", "introduction"}]
            if lines:
                title = " ".join(lines[:2])[:500]

    return {"Title": title, "Authors": authors, "Keywords": keywords, "Abstract": subject}


COLUMN_ALIASES = {
    "paperid": "PaperID", "paper_id": "PaperID", "id": "PaperID",
    "topic": "Topic", "category": "Topic", "section": "Topic", "folder": "Topic",
    "title": "Title", "paper title": "Title", "paper_title": "Title",
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
    compact = key.replace(" ", "")
    return COLUMN_ALIASES.get(key) or COLUMN_ALIASES.get(compact)


def read_uploaded_csv(uploaded) -> tuple[list[dict[str, str]], list[str], list[str]]:
    raw = uploaded.read()
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.reader(text.splitlines(), dialect)
    all_rows = list(reader)
    while all_rows and not any(str(v).strip() for v in all_rows[0]):
        all_rows.pop(0)
    if not all_rows:
        return [], [], []

    headers = [str(h or "").strip() for h in all_rows[0]]
    mapped_headers = [canonical_column(h) for h in headers]
    recognized = [h for h in mapped_headers if h]
    unknown_headers = [headers[i] for i, mapped in enumerate(mapped_headers) if not mapped and headers[i]]
    if not recognized:
        raise ValueError("The CSV does not contain any recognized paper-manager columns.")

    imported: list[dict[str, str]] = []
    for values in all_rows[1:]:
        if not any(str(v).strip() for v in values):
            continue
        row: dict[str, str] = {}
        extras: dict[str, str] = {}
        for i, value in enumerate(values):
            value = str(value or "").strip()
            if i < len(mapped_headers) and mapped_headers[i]:
                col = mapped_headers[i]
                if value:
                    row[col] = value
            elif i < len(headers) and headers[i] and value:
                extras[headers[i]] = value
            elif value:
                extras[f"ExtraColumn{i+1}"] = value
        if extras:
            extra_text = "Imported extra fields: " + json.dumps(extras, ensure_ascii=False)
            row["Notes"] = (row.get("Notes", "") + " | " + extra_text).strip(" |")
        imported.append(row)
    return imported, recognized, unknown_headers


def import_match_key(row: dict[str, str]) -> tuple[str, str]:
    if row.get("PaperID"):
        return "PaperID", row["PaperID"]
    if row.get("SHA256"):
        return "SHA256", row["SHA256"].lower()
    if row.get("DOI"):
        return "DOI", row["DOI"].lower().strip()
    if row.get("Path"):
        return "Path", str(Path(row["Path"]).expanduser())
    if row.get("Filename"):
        return "Filename", row["Filename"].lower().strip()
    if row.get("Title") and not is_missing_title(row["Title"]):
        return "Title", normalize_title(row["Title"])
    return "", ""


def merge_imported_rows(
    existing: list[dict[str, str]],
    incoming: list[dict[str, str]],
    create_unmatched: bool = False,
) -> tuple[list[dict[str, str]], dict[str, int]]:
    """Transfer metadata without changing the physical library layout.

    Topic, Path, Filename, FileState, SHA256, OriginalPath, and ArchivedAt are
    protected. CSV import is therefore an information-transfer operation rather
    than a filesystem operation.
    """
    protected = {"PaperID", "Topic", "Filename", "Path", "FileState", "SHA256", "OriginalPath", "ArchivedAt"}
    transferable = [c for c in DEFAULT_COLUMNS if c not in protected]

    indexes: dict[str, dict[str, dict[str, str]]] = {k: {} for k in ("PaperID", "SHA256", "DOI", "Path", "Filename", "Title")}
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
        incoming_row = {col: str(raw.get(col, "") or "").strip() for col in DEFAULT_COLUMNS}
        candidates = []
        for kind, value in (
            ("PaperID", incoming_row.get("PaperID", "")),
            ("SHA256", incoming_row.get("SHA256", "").lower()),
            ("DOI", incoming_row.get("DOI", "").lower().strip()),
            ("Path", str(Path(incoming_row["Path"]).expanduser()) if incoming_row.get("Path") else ""),
            ("Filename", incoming_row.get("Filename", "").lower().strip()),
            ("Title", normalize_title(incoming_row.get("Title", "")) if not is_missing_title(incoming_row.get("Title", "")) else ""),
        ):
            if value and value in indexes[kind]:
                candidates.append(indexes[kind][value])
        target = candidates[0] if candidates else None
        if target is None and incoming_row.get("Title") and not is_missing_title(incoming_row["Title"]):
            candidate, score = best_bib_match({"title": incoming_row["Title"], "doi": incoming_row.get("DOI", "")}, existing)
            if candidate is not None and score >= 0.94:
                target = candidate

        if target is not None:
            matched += 1
            for col in transferable:
                val = incoming_row.get(col, "")
                if not val:
                    continue
                # Never replace a good title with TITLE NOT FOUND.
                if col == "Title" and is_missing_title(val):
                    continue
                if target.get(col) != val:
                    target[col] = val
                    updated_fields += 1
            target["ModifiedDate"] = datetime.now().isoformat()
        elif create_unmatched:
            new_row = normalize_row(incoming_row)
            new_row["Topic"] = "CSV Import Inbox"
            new_row["Path"] = ""
            new_row["Filename"] = incoming_row.get("Filename", "")
            new_row["FileState"] = "Reference Only"
            new_row["SHA256"] = ""
            new_row["OriginalPath"] = ""
            new_row["ArchivedAt"] = ""
            identity = new_row.get("DOI") or normalize_title(new_row.get("Title", "")) or new_row.get("Filename") or now_stamp()
            new_row["PaperID"] = new_row.get("PaperID") or paper_id_for(identity, new_row.get("Filename") or identity)
            existing.append(new_row)
            created += 1
        else:
            unmatched += 1

    return existing, {"matched": matched, "created": created, "unmatched": unmatched, "updated_fields": updated_fields}

@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def api_get_config():
    return jsonify(load_config())


@app.post("/api/config")
def api_set_config():
    data = request.get_json(force=True)
    root = Path(str(data.get("library_root", "")).strip()).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return jsonify({"error": f"Directory does not exist: {root}"}), 400
    save_config({"library_root": str(root)})
    ensure_manager_dirs(root)
    return jsonify({"ok": True, "library_root": str(root)})


@app.get("/api/library")
def api_library():
    try:
        root = get_library_root()
        return jsonify({"library_root": str(root), "rows": read_report(root)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Job not found."}), 404
        return jsonify(dict(job))


@app.post("/api/sync/start")
def api_sync_start():
    try:
        root = get_library_root()
        data = request.get_json(silent=True) or {}
        detect_moves = bool(data.get("detect_moves", True))
        extract_titles = bool(data.get("extract_titles", True))
        job_id = create_job("sync", "Preparing library scan")

        def task():
            def progress(current, total, message):
                update_job(job_id, current=current, total=total, message=message)
            rows, summary = reconcile_library(root, compute_hashes=detect_moves, progress=progress)
            new_ids = {r.get("PaperID", "") for r in summary.get("new_rows", [])}
            if extract_titles:
                targets = [r for r in rows if r.get("FileState") == "Present" and (r.get("PaperID") in new_ids or is_missing_title(r.get("Title", "")))]
                for i, row in enumerate(targets, 1):
                    update_job(job_id, current=i, total=len(targets), message=f"Extracting title: {row.get('Filename','')}")
                    try:
                        md = extract_pdf_metadata(Path(row["Path"]))
                        for key, val in md.items():
                            if val and (not row.get(key) or (key == "Title" and is_missing_title(row.get(key, "")))):
                                row[key] = val
                    except Exception:
                        pass
            update_job(job_id, message="Validating and writing full report checkpoint")
            before = read_report(root)
            expected_ids = {r.get("PaperID", "") for r in before if r.get("PaperID", "")}
            write_report_atomic(root, rows, "sync_library", expected_ids=expected_ids)
            clean_summary = {k: v for k, v in summary.items() if not k.endswith("_rows")}
            clean_summary["titles_checked"] = len([r for r in rows if r.get("FileState") == "Present"])
            return clean_summary

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/papers/move")
def api_move_paper():
    try:
        root = get_library_root()
        data = request.get_json(force=True)
        paper_id = str(data.get("paper_id", ""))
        destination_topic = str(data.get("destination_topic", "")).strip()
        if not destination_topic or "/" in destination_topic or "\\" in destination_topic:
            return jsonify({"error": "Enter a valid destination topic without path separators."}), 400

        rows = read_report(root)
        row = find_row(rows, paper_id)
        if row["FileState"] != "Present":
            return jsonify({"error": "Only present PDFs can be moved."}), 400
        src = Path(row["Path"]).resolve()
        if not src.exists():
            return jsonify({"error": f"Source PDF does not exist: {src}"}), 400
        dst_dir = root / destination_topic
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name
        if dst.exists() and dst.resolve() != src:
            return jsonify({"error": f"Destination already contains {dst.name}."}), 409

        create_checkpoint(root, "move_paper", [src])
        shutil.move(str(src), str(dst))
        row.update({"Topic": destination_topic, "Path": str(dst.resolve()), "Filename": dst.name, "FileState": "Present"})
        write_report_atomic(root, rows, "move_paper_csv_update", checkpoint=False)
        log_operation(root, "move_paper", {"paper_id": paper_id, "from": str(src), "to": str(dst)})
        return jsonify({"ok": True, "row": row})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/papers/archive")
def api_archive_paper():
    try:
        root = get_library_root()
        paper_id = str(request.get_json(force=True).get("paper_id", ""))
        rows = read_report(root)
        row = find_row(rows, paper_id)
        if row["FileState"] != "Present":
            return jsonify({"error": "Only present PDFs can be archived."}), 400
        src = Path(row["Path"]).resolve()
        if not src.exists():
            return jsonify({"error": f"Source PDF does not exist: {src}"}), 400

        stamp = now_stamp()
        rel = src.relative_to(root)
        dst = manager_dir(root) / "deleted_pdfs" / stamp / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        create_checkpoint(root, "archive_paper", [src])
        shutil.move(str(src), str(dst))
        row.update({
            "OriginalPath": str(src),
            "ArchivedAt": datetime.now().isoformat(),
            "Path": str(dst.resolve()),
            "FileState": "Deleted",
        })
        write_report_atomic(root, rows, "archive_paper_csv_update", checkpoint=False)
        log_operation(root, "archive_paper", {"paper_id": paper_id, "from": str(src), "archive": str(dst)})
        return jsonify({"ok": True, "row": row})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/papers/restore")
def api_restore_paper():
    try:
        root = get_library_root()
        data = request.get_json(force=True)
        paper_id = str(data.get("paper_id", ""))
        destination_topic = str(data.get("destination_topic", "")).strip()
        rows = read_report(root)
        row = find_row(rows, paper_id)
        if row["FileState"] != "Deleted":
            return jsonify({"error": "Only archived PDFs can be restored."}), 400
        src = Path(row["Path"]).resolve()
        if not src.exists():
            return jsonify({"error": f"Archived PDF does not exist: {src}"}), 400

        if destination_topic:
            if "/" in destination_topic or "\\" in destination_topic:
                return jsonify({"error": "Invalid destination topic."}), 400
            dst = root / destination_topic / row["Filename"]
        elif row.get("OriginalPath"):
            dst = Path(row["OriginalPath"]).resolve()
            try:
                dst.relative_to(root)
            except ValueError:
                return jsonify({"error": "Original path is outside the configured library."}), 400
        else:
            dst = root / row["Topic"] / row["Filename"]

        if dst.exists():
            return jsonify({"error": f"Restore destination already exists: {dst}"}), 409
        dst.parent.mkdir(parents=True, exist_ok=True)
        create_checkpoint(root, "restore_paper", [src])
        shutil.move(str(src), str(dst))
        rel = dst.relative_to(root)
        topic = rel.parts[0] if len(rel.parts) > 1 else "Uncategorized"
        row.update({
            "Topic": topic,
            "Path": str(dst.resolve()),
            "Filename": dst.name,
            "FileState": "Present",
            "OriginalPath": "",
            "ArchivedAt": "",
        })
        write_report_atomic(root, rows, "restore_paper_csv_update", checkpoint=False)
        log_operation(root, "restore_paper", {"paper_id": paper_id, "from": str(src), "to": str(dst)})
        return jsonify({"ok": True, "row": row})
    except KeyError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/report")
def api_save_report():
    try:
        root = get_library_root()
        rows = request.get_json(force=True).get("rows", [])
        if not isinstance(rows, list):
            return jsonify({"error": "rows must be a list."}), 400
        current = read_report(root)
        expected_ids = {r.get("PaperID", "") for r in current if r.get("PaperID", "")}
        write_report_atomic(root, rows, "save_metadata", expected_ids=expected_ids)
        return jsonify({"ok": True, "rows_written": len(rows)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/history")
def api_history():
    try:
        root = get_library_root()
        path = manager_dir(root) / "logs" / "operations.jsonl"
        records = []
        if path.exists():
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return jsonify({"history": records[-100:][::-1]})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.get("/api/checkpoints")
def api_checkpoints():
    try:
        root = get_library_root()
        base = manager_dir(root) / "checkpoints"
        checkpoints = []
        if base.exists():
            for cp in sorted(base.iterdir(), reverse=True):
                if not cp.is_dir():
                    continue
                meta_path = cp / "operation.json"
                meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
                checkpoints.append({
                    "name": cp.name,
                    "created_at": meta.get("created_at", ""),
                    "operation": meta.get("operation", "unknown"),
                    "copied_files": meta.get("copied_files", []),
                    "has_report": (cp / "paper_report.csv").exists(),
                })
        return jsonify({"checkpoints": checkpoints[:100]})
    except Exception as e:
        return jsonify({"error": str(e)}), 400



@app.post("/api/csv/import")
def api_csv_import():
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
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/bib/import")
def api_bib_import():
    try:
        root = get_library_root()
        uploaded = request.files.get("file")
        if not uploaded:
            return jsonify({"error": "Choose a .bib file."}), 400
        text = uploaded.read().decode("utf-8", errors="replace")
        entries = [x for x in (parse_bib_entry(e) for e in split_bib_entries(text)) if x]
        job_id = create_job("bib_import", f"Parsed {len(entries)} BibTeX entries")

        def task():
            rows = read_report(root)
            matched, created, uncertain = 0, 0, []
            today = datetime.now().isoformat()
            for i, entry in enumerate(entries, 1):
                update_job(job_id, current=i, total=len(entries), message=f"Matching BibTeX entry {i} of {len(entries)}")
                row, score = best_bib_match(entry, rows)
                title = entry.get("title", "") or "TITLE NOT FOUND"
                values = {
                    "Title": title, "Authors": entry.get("author", ""), "Year": entry.get("year", ""),
                    "Venue": entry.get("journal", "") or entry.get("booktitle", "") or entry.get("publisher", ""),
                    "DOI": entry.get("doi", ""), "BibKey": entry.get("BibKey", ""),
                    "Abstract": entry.get("abstract", ""), "Keywords": entry.get("keywords", ""), "ModifiedDate": today,
                }
                if row is not None and score >= 0.82:
                    for key, val in values.items():
                        if val and (not row.get(key) or key in {"Authors", "Year", "Venue", "DOI", "BibKey", "Abstract", "Keywords"}):
                            row[key] = val
                    if row.get("Status") in {"", "Needs Review", "OK"}: row["Status"] = "Cited"
                    matched += 1
                else:
                    new_row = normalize_row({**values, "Topic": "BibTeX Inbox", "Status": "Cited", "FileState": "Reference Only", "PaperID": paper_id_for(entry.get("doi", "") or normalize_title(title), entry.get("BibKey", title))})
                    rows.append(new_row); created += 1
                    if row is not None: uncertain.append({"bib_title": title, "candidate": row.get("Title", ""), "score": round(score, 3)})
            update_job(job_id, message="Writing BibTeX metadata to report")
            write_report_atomic(root, rows, "import_bibtex")
            return {"matched": matched, "created": created, "uncertain": uncertain[:100], "entries": len(entries)}

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/metadata/extract")
def api_metadata_extract():
    try:
        root = get_library_root()
        data = request.get_json(silent=True) or {}
        paper_id = str(data.get("paper_id", ""))
        job_id = create_job("metadata_extract", "Preparing PDF metadata extraction")

        def task():
            with LIBRARY_WRITE_LOCK:
                rows = read_report(root)
                if not rows:
                    raise RuntimeError("The current paper_report.csv contains no records; extraction was cancelled without writing.")
                original_ids = {r.get("PaperID", "") for r in rows if r.get("PaperID", "")}
                targets = [find_row(rows, paper_id)] if paper_id else [r for r in rows if r.get("FileState") == "Present"]
                updated, errors = 0, []
                for i, row in enumerate(targets, 1):
                    update_job(job_id, current=i, total=len(targets), message=f"Reading {row.get('Filename','')}")
                    try:
                        path = Path(row["Path"])
                        if not path.exists():
                            errors.append({"paper_id": row.get("PaperID"), "error": f"File not found: {path}"})
                            continue
                        md = extract_pdf_metadata(path)
                        changed = False
                        for key, val in md.items():
                            if val and (not row.get(key) or (key == "Title" and is_missing_title(row.get(key, "")))):
                                row[key] = val
                                changed = True
                        if changed:
                            row["ModifiedDate"] = datetime.now().isoformat()
                            updated += 1
                    except Exception as exc:
                        errors.append({"paper_id": row.get("PaperID"), "error": f"{type(exc).__name__}: {exc}"})
                update_job(job_id, message="Validating and writing extracted metadata")
                write_report_atomic(
                    root,
                    rows,
                    "extract_pdf_metadata",
                    expected_ids=original_ids,
                )
                return {"updated": updated, "processed": len(targets), "errors": errors[:50], "rows_preserved": len(rows)}

        run_job(job_id, task)
        return jsonify({"ok": True, "job_id": job_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.post("/api/checkpoints/restore-latest")
def api_restore_latest_checkpoint():
    try:
        root = get_library_root()
        with LIBRARY_WRITE_LOCK:
            checkpoints_root = manager_dir(root) / "checkpoints"
            candidates = sorted(
                [d for d in checkpoints_root.iterdir() if d.is_dir() and (d / "paper_report.csv").exists()],
                reverse=True,
            ) if checkpoints_root.exists() else []
            if not candidates:
                return jsonify({"error": "No checkpoint containing paper_report.csv was found."}), 404

            latest = candidates[0]
            source = latest / "paper_report.csv"
            # Preserve the current state before restoring, even if it is damaged.
            emergency = manager_dir(root) / "checkpoints" / f"before_restore_{now_stamp()}"
            emergency.mkdir(parents=True, exist_ok=True)
            current = report_path(root)
            if current.exists():
                shutil.copy2(current, emergency / "paper_report.csv")
            shutil.copy2(source, emergency / "restored_from.txt") if False else None

            tmp = root / "paper_report.restore.tmp"
            shutil.copy2(source, tmp)
            with tmp.open("r", encoding="utf-8-sig", newline="") as f:
                restored_rows = [normalize_row(dict(row)) for row in csv.DictReader(f)]
            if not restored_rows:
                tmp.unlink(missing_ok=True)
                raise RuntimeError("The latest checkpoint report is empty; restore was cancelled.")
            os.replace(tmp, current)
            log_operation(root, "restore_latest_report_checkpoint", {
                "checkpoint": latest.name,
                "rows_restored": len(restored_rows),
            })
            return jsonify({"ok": True, "checkpoint": latest.name, "rows_restored": len(restored_rows)})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 400


@app.get("/api/duplicates")
def api_duplicates():
    try:
        rows = read_report(get_library_root())
        groups=[]; used=set()
        for i,a in enumerate(rows):
            if a.get("PaperID") in used: continue
            group=[a]
            for b in rows[i+1:]:
                same_hash = a.get("SHA256") and a.get("SHA256") == b.get("SHA256")
                same_doi = a.get("DOI") and a.get("DOI").lower() == b.get("DOI", "").lower()
                sim = title_similarity(a.get("Title", ""), b.get("Title", ""))
                if same_hash or same_doi or (sim >= 0.94 and "title not found" not in normalize_title(a.get("Title", ""))):
                    group.append({**b, "Similarity": round(sim, 3)})
            if len(group)>1:
                groups.append(group)
                used.update(r.get("PaperID") for r in group)
        return jsonify({"groups": groups, "count": len(groups)})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)