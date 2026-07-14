# Migration Stage 3

The Flask API has been split into feature blueprints:

- `config_routes.py`
- `job_routes.py`
- `library_routes.py`
- `paper_routes.py`
- `import_routes.py`
- `metadata_routes.py`
- `checkpoint_routes.py`

`backend/app.py` now only creates the Flask application, registers blueprints,
and serves the frontend.

CSV import logic now lives in `backend/services/csv_import.py`.

`legacy_app.py` remains in the repository as a temporary reference, but it is no
longer imported by the runnable application.
