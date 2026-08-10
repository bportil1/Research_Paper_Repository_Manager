# Architecture

The reference manager has two layers:

```text
Standalone Web UI
       |
       v
ReferenceManager public API
       |
       +--> library/   filesystem and CSV report persistence
       +--> services/  imports, metadata, duplicates, checkpoints
       +--> models/    paper domain model
```

## Core rules

1. The filesystem is authoritative for PDF presence and location.
2. `paper_report.csv` stores user metadata and stable paper identifiers.
3. `ReferenceManager` is the supported public integration surface.
4. Core modules do not import Flask or web routes.
5. Flask routes are adapters: they translate HTTP requests into core API calls.
6. Long-running standalone UI operations use the job manager, but the core API
   itself remains synchronous and callable from any host application.
7. Local standalone configuration is not part of the reusable core. A host
   application should construct `ReferenceManager` with an explicit library path.
8. Cross-project behavior belongs in the future host application, not in this module.

## Runtime data

The selected paper library contains:

```text
paper_library/
├── paper_report.csv
├── Topic A/
├── Topic B/
└── .paper_manager/
    ├── checkpoints/
    ├── deleted_pdfs/
    └── logs/
```

The repository's own `config.json` stores only the standalone UI's selected
library path and is ignored by version control.
