"""Portable, exact basis-point mixtures. No machine-local adapter paths persist."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import HTTPException
from pydantic import Field, StrictInt, model_validator

from server.modules.lora_reference import LoraReference
from server.modules.request_model import StrictRequestModel


class LoraMixEntry(StrictRequestModel):
    assetId: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    adapterHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    baseModelRepo: str = Field(min_length=1, max_length=200)
    baseModelRevision: str = Field(min_length=1, max_length=128)
    weight: StrictInt = Field(ge=0, le=10000)


class LoraMix(StrictRequestModel):
    version: Literal[1] = 1
    baseWeight: StrictInt = Field(ge=0, le=10000)
    entries: list[LoraMixEntry] = Field(max_length=4)

    @model_validator(mode="after")
    def exact_total(self):
        if self.baseWeight + sum(item.weight for item in self.entries) != 10000:
            raise ValueError("LoRA配合の合計は100%にしてください。")
        if len({item.assetId for item in self.entries}) != len(self.entries):
            raise ValueError("同じLoRAは重複追加できません。")
        return self


def effective_mix(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("loraMix") is not None:
        return LoraMix.model_validate(item["loraMix"]).model_dump()
    legacy = item.get("lora")
    if legacy is None:
        return {"version": 1, "baseWeight": 10000, "entries": []}
    reference = LoraReference.model_validate(legacy).model_dump()
    enabled = reference.pop("enabled")
    return {"version": 1, "baseWeight": 0 if enabled else 10000,
            "entries": [{**reference, "weight": 10000 if enabled else 0}]}


def resolve_mix(mix: dict[str, Any]) -> dict[str, Any] | None:
    from server.modules.lora_assets import resolve_lora_asset
    validated = LoraMix.model_validate(mix).model_dump()
    # Resolve every positive member before returning an executable descriptor.
    adapters = [{**resolve_lora_asset({**item, "enabled": True}), "weight": item["weight"]}
                for item in validated["entries"] if item["weight"] > 0]
    if not adapters:
        return None
    return {"version": 1, "baseWeight": validated["baseWeight"], "adapters": adapters}


def generation_mix(character: dict[str, Any], take: dict[str, Any] | None):
    # Never borrow the current cast's mixture when restoring a legacy Take.
    source = take if take is not None else character
    try:
        mix = effective_mix(source)
        return mix, resolve_mix(mix)
    except ValueError as error:
        raise HTTPException(409, "保存されたLoRA配合が不正です。キャスト設定を確認してください。") from error

def apply_mix_patch(character: dict[str, Any], request) -> None:
    if "loraMix" in request.model_fields_set:
        character["loraMix"] = request.loraMix.model_dump() if request.loraMix is not None else None
    if "lora" in request.model_fields_set:
        character["lora"] = request.lora.model_dump() if request.lora is not None else None
