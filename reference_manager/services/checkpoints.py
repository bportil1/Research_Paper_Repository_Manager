from __future__ import annotations
import csv, json, shutil
from datetime import datetime
from pathlib import Path
from reference_manager.constants import DEFAULT_COLUMNS
from reference_manager.library.paths import ensure_manager_dirs, manager_dir, report_path

def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")

def create_checkpoint(root: Path, operation: str, include_files: list[Path]) -> Path:
    from reference_manager.library.scanner import reconcile_library
    ensure_manager_dirs(root)
    checkpoint = manager_dir(root)/"checkpoints"/now_stamp(); checkpoint.mkdir(parents=True, exist_ok=True)
    current = report_path(root)
    if current.exists(): shutil.copy2(current, checkpoint/"paper_report.csv")
    manifest, _ = reconcile_library(root, compute_hashes=False)
    with (checkpoint/"library_manifest.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=DEFAULT_COLUMNS, quoting=csv.QUOTE_ALL, escapechar="\\", doublequote=True); writer.writeheader(); writer.writerows(manifest)
    copied=[]
    for src in include_files:
        if src.exists() and src.is_file():
            try: relative = src.resolve().relative_to(root.resolve())
            except ValueError: relative = Path(src.name)
            dst = checkpoint/"files"/relative; dst.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(src,dst); copied.append(str(relative))
    (checkpoint/"operation.json").write_text(json.dumps({"created_at": datetime.now().isoformat(), "operation": operation, "copied_files": copied}, indent=2), encoding="utf-8")
    return checkpoint

def list_checkpoints(root: Path) -> list[dict[str, object]]:
    base=manager_dir(root)/"checkpoints"; output=[]
    if not base.exists(): return output
    for cp in sorted(base.iterdir(), reverse=True):
        if not cp.is_dir(): continue
        meta_path=cp/"operation.json"; meta=json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        output.append({"name":cp.name,"created_at":meta.get("created_at",""),"operation":meta.get("operation","unknown"),"copied_files":meta.get("copied_files",[]),"has_report":(cp/"paper_report.csv").exists()})
    return output[:100]
