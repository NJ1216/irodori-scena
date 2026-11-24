"""Fail closed when restoring a Take with a different runtime or decoder."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


RUNTIME_FIELDS = ("variantId", "backend", "precision", "artifactRepo", "artifactRevision")
CODEC_FIELDS = {"codecArtifactRepo": "repo", "codecArtifactRevision": "revision", "codecPrecision": "precision"}


def _same(left: Any, right: Any, *, precision: bool = False) -> bool:
    return str(left).casefold() == str(right).casefold() if precision else left == right


def validate_take_runtime(saved: dict[str, Any], runtime: dict[str, Any] | None) -> None:
    expected = {key: saved[key] for key in RUNTIME_FIELDS if saved.get(key) is not None}
    if not expected:
        return  # Legacy Takes have only the original engine/base/Codec identities.
    model = (runtime or {}).get("model") or {}
    current = {**model, "artifactRepo": model.get("repo"), "artifactRevision": model.get("revision")}
    if any(not _same(value, current.get(key), precision=key == "precision") for key, value in expected.items()):
        raise HTTPException(409, "保存済みTakeと同じ音声エンジン・モデル形式・精度を選択してください。")


def validate_take_execution(saved: dict[str, Any], execution: dict[str, Any]) -> None:
    expected = {key: saved[key] for key in RUNTIME_FIELDS if saved.get(key) is not None}
    if any(not _same(value, execution.get(key), precision=key == "precision") for key, value in expected.items()):
        raise HTTPException(409, "保存済みTakeと異なる実行構成のため復元を中止しました。")
    codec = execution.get("codec") or {}
    if any(saved.get(key) is not None and not _same(saved[key], codec.get(field), precision=field == "precision") for key, field in CODEC_FIELDS.items()):
        raise HTTPException(409, "保存済みTakeと異なる実際のCodecのため復元を中止しました。")
