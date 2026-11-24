"""PAH module-process contract for the standalone Reference Manager interface.

PAH owns instance IDs, ports, logs and subprocess supervision. Reference Manager
owns its library selection, jobs, CSV reports and local PDF files. This adapter
returns a trusted command; it never launches a process by itself.
"""
from __future__ import annotations

from importlib.util import find_spec
from pathlib import Path
import sys
from typing import Any, Mapping


def _value(context: Any, name: str) -> Any:
    return context.get(name) if isinstance(context, Mapping) else getattr(context, name, None)


def _initial_library(context: Any) -> Path | None:
    resources = _value(context, "resources")
    resources = resources if isinstance(resources, Mapping) else {}
    # A PAH workspace can explicitly register a reference-library resource.
    # Never silently reinterpret the PAH repository/project root as a PDF library.
    value = next((resources[k] for k in ("reference_library", "references", "papers")
                  if resources.get(k) is not None), None)
    if value is None:
        return None
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError(f"Reference library is not a directory: {root}")
    return root


class ReferenceManagerRuntimeAdapter:
    module_id = "reference_manager"

    def status(self, *, context: Any = None) -> dict[str, Any]:
        available = find_spec("flask") is not None
        try:
            library = _initial_library(context)
            error = None
        except (OSError, ValueError) as exc:
            library = None
            error = str(exc)
        return {
            "module_id": self.module_id,
            "available": available,
            "running": False,  # PAH owns the running-process registry.
            "launchable": available and error is None,
            "presentation": "module_process",
            "message": error or (
                "Open a new Reference Manager instance from PAH Instances."
                if available else "The standalone web UI requires Flask."
            ),
            "initial_library": str(library) if library else None,
        }

    def launch(self, *, context: Any = None, detached: bool = False) -> dict[str, Any]:
        # The legacy hosted References surface remains available separately.
        # Do not spawn unregistered children through a module-type launch.
        return {
            "module_id": self.module_id,
            "launched": False,
            "message": "Use New Instance in PAH Instances or the legacy References surface.",
        }

    def shutdown(self, *, context: Any = None) -> None:
        # PAH closes its own children by unique instance ID.
        return None

    def process_launch_spec(self, *, context: Any = None) -> dict[str, Any]:
        if find_spec("flask") is None:
            raise RuntimeError("Independent Reference Manager UI requires Flask (install the 'web' extra)")
        library = _initial_library(context)
        return {
            "command": [sys.executable, "-m", "reference_manager.process_ui"],
            # Explicitly clear inherited initial-library values when the selected
            # PAH workspace has no library resource.
            "env": {"REFERENCE_MANAGER_INITIAL_LIBRARY": str(library) if library else ""},
            "requested_port": 0,
            "ui_path": "/",
        }


def create_runtime_adapter() -> ReferenceManagerRuntimeAdapter:
    """Entry-point factory for PAH's callable-based adapter discovery."""
    return ReferenceManagerRuntimeAdapter()
