from __future__ import annotations
import re
from typing import Any

def sanitize_text(value: Any) -> str:
    text = str(value or "").replace("\x00", " ")
    text = "".join(ch if ch in "\t\n\r" or ord(ch) >= 32 else " " for ch in text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def normalize_title(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value).lower()).split())

def is_missing_title(value: str) -> bool:
    normalized = normalize_title(value)
    return not normalized or normalized in {"title not found", "error reading pdf"} or normalized.startswith("error reading pdf")
