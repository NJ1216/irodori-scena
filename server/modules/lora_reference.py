"""Portable adapter identity; machine-local paths are resolved only at execution."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import Field, ValidationError

from server.modules.request_model import StrictRequestModel


class LoraReference(StrictRequestModel):
    assetId: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    adapterHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseModelRepo: str = Field(min_length=1, max_length=200)
    baseModelRevision: str = Field(min_length=1, max_length=128)
    enabled: bool


def generation_lora(character: dict[str, Any], take: dict[str, Any] | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    # Legacy takes were generated without adapters, even if the cast changed later.
    raw = take.get("lora") if take is not None else character.get("lora")
    if raw is None:
        return None, None
    try:
        reference = LoraReference.model_validate(raw).model_dump()
    except ValidationError as error:
        raise HTTPException(status_code=409, detail="保存されたLoRA設定が不正です。キャスト設定を確認してください。") from error
    if not reference["enabled"]:
        return reference, None
    from server.modules.lora_assets import resolve_lora_asset
    return reference, resolve_lora_asset(reference)


def lora_portability_warnings(characters: list[dict[str, Any]]) -> list[str]:
    return [
        f"キャスト「{item.get('name', '')}」のLoRA本体は同梱されません。設定は保持されますが、別の環境では同じadapterの登録が必要です。"
        for item in characters if item.get("lora") is not None or item.get("loraMix") is not None
    ]
