from pathlib import Path
from reference_manager.constants import IGNORED_DIRS

def manager_dir(root: Path) -> Path: return root / ".paper_manager"
def report_path(root: Path) -> Path: return root / "paper_report.csv"
def ensure_manager_dirs(root: Path) -> None:
    for child in ("checkpoints", "deleted_pdfs", "logs"):
        (manager_dir(root) / child).mkdir(parents=True, exist_ok=True)
def filesystem_pdfs(root: Path) -> list[Path]:
    return [p for p in sorted(root.rglob("*.pdf")) if not any(part in IGNORED_DIRS for part in p.relative_to(root).parts)]
