# Paper Library Manager v6

Reliability-focused release.

## Main fixes

- Long-running Sync, BibTeX import, CSV transfer, and PDF metadata extraction now run as tracked jobs with visible progress.
- Library synchronization no longer hashes every existing PDF on every run. Existing paths are fast; only new paths are hashed when move/rename detection is enabled.
- CSV import is now **metadata transfer only by default**. It cannot change topic folders, paths, filenames, hashes, archive state, or move files.
- Unmatched CSV rows are skipped by default. You can optionally create them as reference-only records under `CSV Import Inbox`.
- A good title is never replaced by `TITLE NOT FOUND`.
- Sync can extract missing titles from the first page while displaying the current PDF and count.
- Every saved report still uses the complete master schema.

## Run

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:8765`.

## Recommended recovery from the bad v5 import

Use a checkpoint created before the CSV import, or restore your previous `paper_report.csv`. Then start v6 and run Sync with both checkboxes enabled. CSV transfer should only be used after the real directory has been synchronized.

## v8 data-safety changes

- All report writes use a single-writer lock.
- A nonempty report can no longer be replaced by an empty report.
- Metadata extraction must preserve every existing PaperID.
- Sync must preserve all existing records and will abort before writing if any would be lost.
- Duplicate PaperID values abort the write.
- Background job failures display the exact exception and expandable traceback.
- **More → Restore Latest Report Checkpoint** restores the newest nonempty checkpoint while preserving the current report in an emergency checkpoint.


## v8 PaperID repair

- Duplicate or blank legacy `PaperID` values are repaired automatically during any safe report write.
- The first occurrence keeps its original ID. Additional rows receive deterministic IDs based on file identity and path.
- No rows are deleted or merged. Repairs are recorded in `.paper_manager/logs/operations.jsonl`.


## v9 CSV serialization fix

All CSV writers now use:

- `csv.QUOTE_ALL`
- `escapechar="\\"`
- `doublequote=True`

This prevents `_csv.Error: need to escape, but no escapechar set` when extracted PDF metadata contains embedded quotes, backslashes, delimiters, or unusual control text.

The existing checkpoint, rollback, duplicate-ID repair, and single-writer protections remain unchanged.


## v10 NUL/control-character sanitization

PDF metadata and first-page text can contain binary control characters, including NUL (`\x00`).
Python's CSV reader rejects those values even when quoting and escaping are configured.

v10 sanitizes every report field before writing:

- removes NUL bytes;
- removes unsafe C0 control characters;
- preserves readable tabs and line breaks;
- normalizes repeated whitespace;
- performs a final defensive sanitization immediately before serialization.

Existing checkpoint, rollback, duplicate-ID repair, and single-writer protections remain enabled.
