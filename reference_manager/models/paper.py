from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any
from reference_manager.constants import ALLOWED_STATUSES, DEFAULT_COLUMNS
from reference_manager.utils.text import sanitize_text

@dataclass(slots=True)
class Paper:
    PaperID: str = ""; Topic: str = "Uncategorized"; Title: str = "TITLE NOT FOUND"
    Filename: str = ""; Path: str = ""; Status: str = "Needs Review"; Notes: str = ""
    Year: str = ""; Authors: str = ""; Venue: str = ""; DOI: str = ""; BibKey: str = ""
    Abstract: str = ""; Keywords: str = ""; FileState: str = "Present"; SHA256: str = ""
    OriginalPath: str = ""; ArchivedAt: str = ""; AddedDate: str = ""; ModifiedDate: str = ""

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> "Paper":
        clean = {col: sanitize_text(row.get(col, "")) for col in DEFAULT_COLUMNS}
        clean["Topic"] = clean["Topic"] or "Uncategorized"
        clean["Title"] = clean["Title"] or "TITLE NOT FOUND"
        clean["Status"] = clean["Status"] if clean["Status"] in ALLOWED_STATUSES else "Needs Review"
        clean["FileState"] = clean["FileState"] or "Present"
        clean["AddedDate"] = clean["AddedDate"] or datetime.now().date().isoformat()
        clean["ModifiedDate"] = clean["ModifiedDate"] or datetime.now().isoformat()
        return cls(**clean)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)
