# Migration Stage 2

The existing Flask routes remain in `backend/legacy_app.py`, but the following are now independent modules:

- `backend.library.identity` — hashes and stable IDs
- `backend.library.report` — the only CSV writer
- `backend.library.scanner` — filesystem reconciliation
- `backend.services.checkpoints` — checkpoint creation/listing
- `backend.services.logging_service` — operation log
- `backend.services.pdf_metadata` — PDF title/metadata extraction

The next migration should split routes into blueprints by feature without moving domain logic back into route modules.
