"""Validate the last saved workspace before making it the active project."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from fastapi import HTTPException

from server.registry import deps

logger = logging.getLogger(__name__)


def _restore_container(candidate: Path) -> None:
    signature = deps.container_signature(candidate)
    root = deps.working_root(candidate)
    prepared = root.with_name(f"{root.name}-restore-preflight")
    try:
        deps.extract_container(candidate, prepared)
        raw = json.loads((prepared / "project.json").read_text(encoding="utf-8"))
        deps.StudioProjectModel.model_validate(raw)
        deps.activate_project_container(
            candidate, persist=False, prepared_root=prepared, expected_signature=signature,
        )
    finally:
        shutil.rmtree(prepared, ignore_errors=True)


def restore_active_workspace() -> None:
    deps.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    if deps.APP_STATE_FILE.is_file():
        try:
            state = json.loads(deps.APP_STATE_FILE.read_text(encoding="utf-8"))
            candidate = Path(state.get("activeProjectPath", "")).expanduser()
            if candidate.is_file() and candidate.suffix.lower() == ".scena":
                _restore_container(candidate)
                return
        except (OSError, ValueError, TypeError, AttributeError, HTTPException):
            logger.warning("前回のプロジェクトを復元できませんでした。元ファイルを保持し、未保存の作業領域を開きます。")
    deps.activate_project_root(deps.default_workspace_root(), persist=False)
