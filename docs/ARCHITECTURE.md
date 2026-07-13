# Architecture

- The filesystem is authoritative for PDF presence and location.
- `paper_report.csv` stores metadata.
- Only the report repository should write the CSV.
- Long operations run through the job manager.
- Flask routes should call services; service modules should not import Flask.
- Keep `legacy_app.py` working until every route has been migrated and tested.
