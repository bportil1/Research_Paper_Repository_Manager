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
