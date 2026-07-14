# Paper Manager staged refactor

The existing application remains runnable through `backend/legacy_app.py` while its responsibilities are migrated into focused modules. This avoids breaking the working application during the first refactor commit.

## Run the preserved application

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m backend.app
```

## New module boundaries

- `backend/config.py`: configuration
- `backend/constants.py`: schema and statuses
- `backend/jobs/manager.py`: background jobs
- `backend/models/paper.py`: typed paper model
- `backend/library/paths.py`: library path helpers
- `backend/services/pdf_metadata.py`: PDF metadata/title extraction
- `backend/services/duplicates.py`: duplicate analysis
- `backend/utils/text.py`: sanitization and title normalization

The next commit should move CSV report I/O, scanning, checkpoints, imports, and Flask routes out of `legacy_app.py` one subsystem at a time, with tests after each move.


## Stage 2

Core CSV, filesystem synchronization, identity, checkpoints, logging, and PDF extraction are now outside `legacy_app.py`. Existing endpoints and the v10 frontend are preserved.

## Stage 3

The Flask API is now split into feature blueprints. `backend/app.py` is the
composition root and no longer imports `legacy_app.py`.

Run with:

```bash
python -m backend.app
```


## Stage 4 interface additions

- Click a paper title to open its PDF with the operating-system default viewer.
- Each paper row has a compact action menu:
  - Open PDF
  - Show in Folder
  - Copy Path
  - Edit Title
  - Move to Topic
  - Archive or Restore
- Each topic heading has an Open Folder action.
- Topic sections display live status-count badges.
- A paper's status menu displays counts for every status within that paper's topic.
- The global status filter displays library-wide counts.
