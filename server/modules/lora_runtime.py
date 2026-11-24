"""Resolve pinned, existing assets only: no implicit installation/download."""
from __future__ import annotations
import sys
from pathlib import Path
from fastapi import HTTPException
from huggingface_hub import try_to_load_from_cache
from server.registry import deps
from server.modules.tts_catalog import ENGINE_COMMIT, MODEL_REPO, MODEL_REVISION, CODEC_REVISION
from server.modules.lora_storage import digest
from server.scena_mlx_lora import supports_lora_model

BASE_SHA256 = "c85de88c01700cb53538e706f128ebcb1b8513ad21d7d0e75f58bc82cdbf89f6"
TRAIN_SHA256 = "4e55e0e1e2f3da21830020e4e36ad8ef0cc39f4c47d1206f17f5dc80fb7342c4"
PRESETS = {"check": {"maxSteps": 3, "batchSize": 1, "learningRate": 0.0001, "maxSeconds": None},
           "normal": {"maxSteps": 1000, "batchSize": 1, "learningRate": 0.0001, "maxSeconds": None}}


def base_checkpoint() -> Path:
    registry = deps.read_tts_registry()
    model = next((m for m in registry["models"] if m.get("repo") == MODEL_REPO and m.get("revision") == MODEL_REVISION), {})
    variant = next((v for v in model.get("installedVariants", []) if v.get("id") == "pytorch-fp32"), {})
    candidates = [Path(variant["path"]) / "model.safetensors"] if variant.get("path") else []
    cached = try_to_load_from_cache(MODEL_REPO, "model.safetensors", revision=MODEL_REVISION)
    if isinstance(cached, str):
        candidates.append(Path(cached))
    checkpoint = next((p for p in candidates if p.is_file()), None)
    if not checkpoint:
        raise HTTPException(409, "公式 v4.1 Small の FP32 本体モデルが必要です。未導入のため学習できません。")
    return checkpoint


def training_runtime(*, verify: bool = False) -> dict:
    if sys.platform != "darwin":
        raise HTTPException(409, "LoRA 学習の初期対応は Apple Silicon Mac / MPS です。")
    registry = deps.read_tts_registry()
    engine = next((e for e in registry["engines"] if e.get("commit") == ENGINE_COMMIT and e.get("source") == "managed"), {})
    if not engine.get("path") or not engine.get("pythonPath"):
        raise HTTPException(409, "固定版 PyTorch エンジンが必要です。")
    path, python = Path(engine["path"]), Path(engine["pythonPath"])
    codec = deps.TTS_CODECS_ROOT / CODEC_REVISION / "weights.pth"
    if not python.is_file() or not (path / "train.py").is_file() or not codec.is_file():
        raise HTTPException(409, "固定版 PyTorch エンジンと Codec が必要です。")
    checkpoint = base_checkpoint()
    if verify and (digest(checkpoint) != BASE_SHA256 or digest(path / "train.py") != TRAIN_SHA256):
        raise HTTPException(409, "本体モデルまたは trainer の検証に失敗しました。")
    return {"enginePath": str(path), "pythonPath": str(python), "checkpoint": str(checkpoint), "codec": str(codec),
            "baseModelRepo": MODEL_REPO, "baseModelRevision": MODEL_REVISION, "baseModelHash": BASE_SHA256}


def lora_status() -> dict:
    result = {"baseModelRepo": MODEL_REPO, "baseModelRevision": MODEL_REVISION, "presets": PRESETS,
              "estimate": None, "estimateNote": "入力長や設定により変わります。この端末の実測がない設定は見積もれません。"}
    runtime = deps.selected_tts_runtime() or {}
    model = runtime.get("model") or {}
    generation = supports_lora_model(model)
    result.update(generationSupported=generation, generationReason=None if generation else
                  "キャスト LoRA の生成には公式 v4.1 Small の固定 MLX FP16／FP32 を選択してください。")
    try:
        training_runtime()
        return {**result, "supported": True, "reason": None}
    except HTTPException as error:
        return {**result, "supported": False, "reason": error.detail}
