from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from backend.constants import DEFAULT_COLUMNS
from backend.models.paper import Paper
from backend.utils.text import sanitize_text


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def paper_id_for(digest: str, filename: str) -> str:
    identity = digest or filename
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def ensure_unique_paper_ids(rows: list[dict[str, Any]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    normalized = [Paper.from_mapping(row).to_dict() for row in rows]
    normalized = [{col: sanitize_text(row.get(col, "")) for col in DEFAULT_COLUMNS} for row in normalized]
    used: set[str] = set()
    repairs: list[dict[str, str]] = []
    for index, row in enumerate(normalized):
        original = row.get("PaperID", "").strip()
        candidate = original
        if not candidate or candidate in used:
            seed = "|".join([original, row.get("SHA256", ""), row.get("Path", ""), row.get("Filename", ""), row.get("Title", ""), str(index)])
            salt = 0
            while True:
                candidate = hashlib.sha256(f"{seed}|{salt}".encode("utf-8")).hexdigest()[:16]
                if candidate not in used:
                    break
                salt += 1
            row["PaperID"] = candidate
            repairs.append({"old_id": original, "new_id": candidate, "path": row.get("Path", ""), "title": row.get("Title", "")})
        used.add(candidate)
    return normalized, repairs
