# Research Paper Repository Manager

A local, filesystem-first reference manager for research PDFs and BibTeX metadata.
The project is intentionally split into a reusable Python core and a standalone
Flask UI so it can later be embedded in a larger project-assistant application
without importing web code.

## Structure

```text
reference_manager/
├── api.py              # public integration surface
├── library/            # filesystem/report persistence
├── models/             # domain models
├── services/           # BibTeX, CSV, metadata, checkpoints, duplicates
├── utils/               # small shared helpers
└── web/                 # standalone Flask application only
    ├── app.py
    ├── config.py       # standalone local configuration
    ├── jobs.py         # standalone background jobs
    ├── routes/
    └── static/
```

## Run standalone

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

The web UI runs at `http://127.0.0.1:8765`.
On first use, select the local PDF library directory in the UI. `config.json`
is local runtime state and is intentionally ignored by Git.

## Use as a Python module

Only the core dependency is needed when embedding the reference manager without
its Flask interface:

```bash
pip install -r requirements-core.txt
```

```python
from reference_manager import ReferenceManager

manager = ReferenceManager("/path/to/paper/library")
rows = manager.list_papers()
summary = manager.sync(extract_titles=False)
duplicates = manager.find_duplicates()
```

The supported integration boundary is `reference_manager.ReferenceManager`.
External code should not import the Flask routes or reach into internal service
modules unless it is extending this project itself.

## Development

Run the core tests with:

```bash
python -m unittest discover -s tests -v
```

See `docs/ARCHITECTURE.md` and `docs/MODULE_CONTRACT.md` for the module boundary.

## Research Search companion — Sprint 1

The Paper Manager now exposes a **Research Search** toolbar action. It launches
an independent nested module at `modules/paper_searcher` on port `8770` and
opens the search UI in a separate browser window.

The searcher remains independently runnable and does not import Paper Manager
internals. Sprint 1 contains the UI shell only; automated provider retrieval is
added in later sprints.

When the searcher is converted to its own Git repository, add it here as the
Paper Manager's nested submodule and use recursive submodule initialization:

```bash
git submodule update --init --recursive
```
