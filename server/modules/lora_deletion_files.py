"""Delete only SCENA-owned adapter files and related job weight copies."""
from pathlib import Path
import shutil

from fastapi import HTTPException

from server.modules.lora_storage import lora_root, owned_path, read_record


def remove_owned_directory(directory: Path) -> None:
    if directory.is_symlink():
        raise HTTPException(409, "LoRAの保存先が不正です。削除していません。")
    if directory.exists():
        shutil.rmtree(directory)


def delete_adapter_files(identifier: str) -> None:
    jobs_root = lora_root() / "jobs"
    if jobs_root.is_symlink() or (lora_root() / "adapters").is_symlink():
        raise HTTPException(409, "LoRAの保存先が不正です。削除していません。")
    # Inspect every candidate before deleting anything. Never use stored paths.
    removals = [owned_path("adapters", identifier)]
    for record_path in jobs_root.glob("*/record.json"):
        job_dir = owned_path("jobs", record_path.parent.name)
        if job_dir.is_symlink():
            raise HTTPException(409, "LoRAの学習保存先が不正です。")
        job = read_record("jobs", job_dir.name)
        if job.get("adapterId") == identifier:
            removals.append(job_dir / "training")
        if job.get("sourceAdapterId") == identifier:
            removals.append(job_dir / "source-adapter")
    if any(path.is_symlink() for path in removals):
        raise HTTPException(409, "LoRAの保存先が不正です。削除していません。")
    # Delete job weight copies first; leave registration intact if cleanup fails.
    for path in [*removals[1:], removals[0]]:
        remove_owned_directory(path)
