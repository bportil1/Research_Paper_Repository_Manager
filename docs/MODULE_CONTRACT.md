# Module Contract

## Public entry point

```python
from reference_manager import ReferenceManager
```

`ReferenceManager` accepts an explicit local library directory and exposes the
operations intended for the future Project Assistant host.

### Library operations

- `list_papers()`
- `get_paper(paper_id)`
- `save_papers(rows)`
- `sync(...)`
- `extract_metadata(...)`
- `find_duplicates()`

### Import operations

- `import_csv(...)`
- `import_bibtex_text(...)`

### File operations

- `move_paper(...)`
- `archive_paper(...)`
- `restore_paper(...)`

### Recovery/history operations

- `history(...)`
- `checkpoints()`
- `restore_latest_checkpoint()`

## Boundary rules

- A host may import `ReferenceManager` and `Paper` from `reference_manager`.
- A host should not import from `reference_manager.web`.
- This module must not import the code analyzer or technical-document module.
- Cross-module links and workflows belong to the host application's integration layer.
- The standalone web application must remain runnable independently.
