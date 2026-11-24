"""Independent loopback-only Reference Manager web process for PAH instances.

The host supplies process identity, runtime directory, and listen port. This
module does not import PAH, nor does it implement paper-library operations.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


def configuration_from_environment(environment: Mapping[str, str] | None = None) -> dict[str, object]:
    values = os.environ if environment is None else environment
    instance_id = str(values.get("PAH_MODULE_INSTANCE_ID", "")).strip()
    if not instance_id or any(char in instance_id for char in "\r\n\0"):
        raise RuntimeError("PAH_MODULE_INSTANCE_ID must be a nonempty opaque identity")

    raw_runtime = str(values.get("PAH_MODULE_RUNTIME_DIR", "")).strip()
    if not raw_runtime:
        raise RuntimeError("PAH_MODULE_RUNTIME_DIR is required")
    runtime_path = Path(raw_runtime).expanduser()
    if runtime_path.is_symlink() or not runtime_path.is_dir():
        raise RuntimeError("PAH_MODULE_RUNTIME_DIR must be an existing, non-symlink directory")
    runtime = runtime_path.resolve(strict=True)

    try:
        port = int(str(values.get("PAH_MODULE_PORT", "")).strip())
    except ValueError as exc:
        raise RuntimeError("PAH_MODULE_PORT must be an integer") from exc
    if not 1 <= port <= 65535:
        raise RuntimeError("PAH_MODULE_PORT must be between 1 and 65535")

    raw_library = str(values.get("REFERENCE_MANAGER_INITIAL_LIBRARY", "")).strip()
    library = None
    if raw_library:
        library = Path(raw_library).expanduser().resolve(strict=True)
        if not library.is_dir():
            raise RuntimeError("REFERENCE_MANAGER_INITIAL_LIBRARY must be an existing directory")

    return {
        "instance_id": instance_id,
        "runtime_dir": runtime,
        "config_path": runtime / "reference-manager-config.json",
        "initial_library": library,
        "port": port,
        "host": "127.0.0.1",
    }


def main() -> int:
    config = configuration_from_environment()
    # Establish the per-process config BEFORE importing Flask routes. Existing
    # standalone mode still uses the repository's config.json by default.
    os.environ["REFERENCE_MANAGER_CONFIG_PATH"] = str(config["config_path"])
    from reference_manager.web.config import save_config

    save_config({"library_root": str(config["initial_library"] or "")})
    from reference_manager.web.app import create_app

    app = create_app()
    app.run(host=config["host"], port=config["port"], debug=False, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
