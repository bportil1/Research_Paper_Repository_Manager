from __future__ import annotations

import re
from difflib import SequenceMatcher

from backend.utils.text import normalize_title


def split_bib_entries(text: str) -> list[str]:
    entries: list[str] = []
    index = 0
    while True:
        start = text.find("@", index)
        if start < 0:
            break
        brace = text.find("{", start)
        if brace < 0:
            break
        depth = 0
        for position in range(brace, len(text)):
            if text[position] == "{":
                depth += 1
            elif text[position] == "}":
                depth -= 1
                if depth == 0:
                    entries.append(text[start:position + 1])
                    index = position + 1
                    break
        else:
            break
    return entries


def parse_bib_entry(entry: str) -> dict[str, str] | None:
    header = re.match(r"@\s*(\w+)\s*\{\s*([^,\s]+)\s*,", entry, re.DOTALL)
    if header is None:
        return None

    result = {"EntryType": header.group(1), "BibKey": header.group(2)}
    body = entry[header.end():].rstrip()
    if body.endswith("}"):
        body = body[:-1]

    index = 0
    while index < len(body):
        while index < len(body) and (body[index].isspace() or body[index] == ","):
            index += 1

        start = index
        while index < len(body) and (body[index].isalnum() or body[index] in "_-"):
            index += 1
        field = body[start:index].lower().strip()
        if not field:
            index += 1
            continue

        while index < len(body) and body[index].isspace():
            index += 1
        if index >= len(body) or body[index] != "=":
            while index < len(body) and body[index] not in ",\n":
                index += 1
            continue

        index += 1
        while index < len(body) and body[index].isspace():
            index += 1

        if index < len(body) and body[index] == "{":
            depth = 1
            index += 1
            chars: list[str] = []
            while index < len(body) and depth:
                char = body[index]
                if char == "{":
                    depth += 1
                    if depth > 1:
                        chars.append(char)
                elif char == "}":
                    depth -= 1
                    if depth > 0:
                        chars.append(char)
                else:
                    chars.append(char)
                index += 1
            value = "".join(chars)
        elif index < len(body) and body[index] == '"':
            index += 1
            chars = []
            escaped = False
            while index < len(body):
                char = body[index]
                if char == '"' and not escaped:
                    index += 1
                    break
                chars.append(char)
                escaped = char == "\\" and not escaped
                if char != "\\":
                    escaped = False
                index += 1
            value = "".join(chars)
        else:
            start_value = index
            while index < len(body) and body[index] not in ",\n":
                index += 1
            value = body[start_value:index]

        result[field] = re.sub(
            r"\s+",
            " ",
            value.replace("{", "").replace("}", ""),
        ).strip()

    return result


def title_similarity(first: str, second: str) -> float:
    return SequenceMatcher(
        None,
        normalize_title(first),
        normalize_title(second),
    ).ratio()


def best_bib_match(
    entry: dict[str, str],
    rows: list[dict[str, str]],
) -> tuple[dict[str, str] | None, float]:
    doi = entry.get("doi", "").lower().strip()
    if doi:
        for row in rows:
            if row.get("DOI", "").lower().strip() == doi:
                return row, 1.0

    title = entry.get("title", "").strip()
    if not title:
        return None, 0.0

    best_row = None
    best_score = 0.0
    for row in rows:
        score = title_similarity(title, row.get("Title", ""))
        if score > best_score:
            best_row = row
            best_score = score
    return best_row, best_score
