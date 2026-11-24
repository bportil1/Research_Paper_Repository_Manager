# Reference Manager — PAH multi-instance compatibility (MI-01)

## Module ownership

PAH owns module discovery, child process identities, launch ports, logs, and
lifecycle. Reference Manager owns the selected paper library, report CSV,
PDF files, background jobs, metadata extraction, and recovery checkpoints.
The adapter does not import PAH or access its private databases.

## Independent launch contract

The installed `pah.runtimes` entry point `reference_manager` uses an adapter
factory and advertises `process_launch_spec(context=...)`. The adapter returns a trusted command for
`python -m reference_manager.process_ui`, a dynamically assigned port, `/` as
the browser UI path, and an optional initial paper library. The launch method
never starts a process or changes the existing standalone UI.

If PAH provides `context.resources['reference_library']` (also accepts
`references` or `papers`), that folder is the *suggested initial library*.
If no explicit reference-library resource is present, the UI opens unconfigured
and the user selects a library. PAH's repository/working directory is never
assumed to be a paper library.

PAH provides `PAH_MODULE_INSTANCE_ID`, `PAH_MODULE_RUNTIME_DIR`, and
`PAH_MODULE_PORT`. Each child validates these values, binds only to
`127.0.0.1`, and uses a private configuration file under its runtime directory.
Different process ports cannot silently change one another's selected library.
Standalone `python run.py` keeps its default port (8765) and repository-local
`config.json`. The existing legacy PAH hosted References surface is preserved.

The per-instance config is temporary state. If PAH deletes the runtime directory
on shutdown, restarting a module without an explicit reference-library resource
will require selecting its library again.

## Shared data and Research Search boundary

Each library independently owns `paper_report.csv` and `.paper_manager/`.
Different library roots are naturally separated. **Opening the same writable
library in two processes is not a transactionally isolated multi-user workflow**:
`paper_report.csv` uses a process-local lock and may still suffer stale writes.
Prefer separate library roots for concurrent editing until library-level
cross-process locking and conflict checking are implemented.

The nested `modules/paper_searcher` repository was **not present** in the
reviewed source archive. Its legacy launcher targets one fixed
`127.0.0.1:8770` Research Search service for all Reference Manager windows.
MI-01 does not claim independent searcher processes, independent search state,
or ownership verification of any service already listening on port 8770.
A separate Research Search contract review is needed once its source is
available; no provider/network behavior is changed in this patch.

The `.gitignore` changes ignore generated repository-root `/analysis/`,
`/.pah/`, scratch, temporary directories, build outputs, and SQLite sidecars.
They do not ignore the nested Git submodule or legitimate library content.
Already tracked generated files require a separately reviewed `git rm --cached`.

## Local acceptance tests

1. Install Reference Manager with its local web dependencies and discover the
   `reference_manager` entry point from PAH.
2. Open two Reference Manager instances from the PAH Instances dialog and
   verify independent PIDs, ports, logs, and runtime paths.
3. Select different paper libraries in each and confirm that changing the
   selection in one does not change `/api/config` or `/api/library` in the other.
4. Stop one instance from PAH and confirm the other stays running.
5. Open the legacy standalone UI and confirm its repository-local `config.json`
   remains independent of the PAH instance configurations.
6. Treat Research Search as a shared legacy companion until its nested
   repository can be verified; do not assume it has been made multi-instance.
