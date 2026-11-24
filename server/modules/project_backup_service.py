from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from server.registry import deps


def _validate_destination(path: Path) -> Path:
    if not path.is_absolute() or path.suffix.lower() != ".scena":
        raise HTTPException(status_code=422, detail="保存先には.scenaファイルを指定してください。")
    if path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise HTTPException(status_code=422, detail="バックアップ先を安全に開けません。")
    destination = path.parent.resolve() / path.name
    source = deps.ACTIVE_PROJECT_PATH
    if source is not None and destination == source.resolve():
        raise HTTPException(status_code=422, detail="現在のプロジェクト自身にはバックアップできません。")
    if deps.is_within_directory(destination, deps.DATA_ROOT):
        raise HTTPException(status_code=422, detail="SCENA管理領域にはバックアップできません。")
    if destination.exists() and not destination.is_file():
        raise HTTPException(status_code=422, detail="バックアップ先には通常ファイルを指定してください。")
    return destination


def backup_project(destination_path: str) -> dict:
    source = deps.ACTIVE_PROJECT_PATH
    if source is None:
        raise HTTPException(status_code=409, detail="先にプロジェクトを保存してください。")
    destination = _validate_destination(Path(destination_path).expanduser())
    project = deps.read_project()
    if deps.reconcile_project_media(project):
        deps.write_project(project)
    else:
        deps.sync_container(source, deps.ACTIVE_PROJECT_ROOT)
    staging = destination.parent / f".{destination.stem}.staging-{uuid4().hex}.scena"
    previous = destination.parent / f".{destination.stem}.previous-{uuid4().hex}.scena"
    replaced = False
    installed = False
    try:
        with closing(sqlite3.connect(source)) as input_db, closing(sqlite3.connect(staging)) as output_db:
            input_db.backup(output_db)
        deps.validate_container(staging)
        with staging.open("rb") as stream:
            os.fsync(stream.fileno())
        if destination.exists():
            destination.replace(previous)
            replaced = True
        staging.replace(destination)
        installed = True
        previous.unlink(missing_ok=True)
    except Exception:
        if installed:
            destination.unlink(missing_ok=True)
        if replaced and previous.exists():
            previous.replace(destination)
        raise
    finally:
        staging.unlink(missing_ok=True)
        if installed:
            previous.unlink(missing_ok=True)
    return {"project": deps.read_project(), "backup": {"path": str(destination), "name": destination.name}}


deps.register(__name__, ["backup_project"])
