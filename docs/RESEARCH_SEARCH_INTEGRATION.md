# Research Search Integration Contract

## Ownership

`modules/paper_searcher` is owned by the Paper Manager but remains an
independently runnable application.

## Runtime contract

- Paper Manager: `127.0.0.1:8765`
- Research Search: `127.0.0.1:8770`
- Paper Manager launches `modules/paper_searcher/run.py` when required.
- Paper Manager opens `http://127.0.0.1:8770/research-search` in a separate window.

## Boundary

The searcher does not import `reference_manager` code. The Paper Manager does
not import search provider implementations. Integration is process/HTTP based.

## Git

The intended repository layout is:

```text
Research_Paper_Repository_Manager/
└── modules/
    └── paper_searcher/    # nested Git submodule
```

The top-level host therefore only needs recursive submodule initialization.
