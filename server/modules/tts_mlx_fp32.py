"""Local-only MLX FP32 composition; no duplicate checkpoint."""
from __future__ import annotations

import platform
import sys
from pathlib import Path
from typing import Any

BASE_REPO = "Aratako/Irodori-TTS-v4.1-Small"
BASE_REVISION = "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
VARIANT_ID = "mlx-fp32"


def cached_base_path() -> Path | None:
    # This API consults local cache only; it never calls Hugging Face or downloads.
    from huggingface_hub import try_to_load_from_cache

    found = try_to_load_from_cache(BASE_REPO, "model.safetensors", revision=BASE_REVISION)
    return Path(found).parent if isinstance(found, str) and Path(found).is_file() else None


def add_local_fp32_variants(registry: dict[str, Any]) -> None:
    for model in registry["models"]:
        model["installedVariants"] = [item for item in model.get("installedVariants", []) if item.get("id") != VARIANT_ID]
    if sys.platform != "darwin" or platform.machine().lower() not in {"arm64", "aarch64"}:
        return
    engine = next((item for item in registry["engines"] if item.get("id") == "mlx-audio@0.5.0"), {})
    for model in registry["models"]:
        if (model.get("repo"), model.get("revision")) != (BASE_REPO, BASE_REVISION):
            continue
        variants = [item for item in model.get("installedVariants", []) if item.get("id") != VARIANT_ID]
        model["installedVariants"] = variants
        base = next((item for item in variants if item.get("id") == "pytorch-fp32"), {})
        codec = next((item for item in variants if item.get("id") == "mlx-fp16"), {})
        base_path = Path(str(base["path"])) if base.get("path") else cached_base_path()
        codec_path = Path(str(codec.get("path") or ""))
        if base_path is None:
            continue
        required = (base_path / "model.safetensors", codec_path / "config.json",
                    codec_path / "dacvae" / "model.safetensors", codec_path / "dacvae" / "config.json",
                    codec_path / "tokenizer", Path(str(engine.get("pythonPath") or "")))
        if not codec or not engine.get("pythonPath") or not all(path.exists() for path in required):
            continue
        variants.append({
            "id": VARIANT_ID, "displayName": "MLX FP32（LoRA対応）", "precision": "FP32", "backend": "mlx",
            "repo": BASE_REPO, "revision": BASE_REVISION, "path": str(base_path),
            "mlxAssetsPath": str(codec_path), "codecPath": str(codec_path / "dacvae"),
            "mlxAssetsRepo": codec.get("repo") or "mlx-community/Irodori-TTS-v4.1-Small-fp16",
            "mlxAssetsRevision": codec.get("revision") or "8be8d91091380115f1ac77aeb6604ed588d05372",
            "optimizationProfile": "mlx-audio-0.5.0-fp32", "diskBytes": 0,
            "runtimeEngineId": "mlx-audio@0.5.0", "derivedLocal": True,
        })


def fp32_catalog_variant(repo, revision, model_sha) -> dict[str, Any] | None:
    if (repo, revision) != (BASE_REPO, BASE_REVISION):
        return None
    return {"id": VARIANT_ID, "displayName": "MLX FP32（LoRA対応）", "precision": "FP32", "backend": "mlx",
            "repo": repo, "revision": revision, "modelSha256": model_sha, "sizeBytes": 0,
            "supportedOs": ["macos"], "supportedCpu": ["arm64"], "supportedEngineIds": [],
            "runtimePackage": "mlx-audio==0.5.0", "runtimeProfile": "mlx-audio-0.5.0-fp32", "visible": sys.platform == "darwin",
            "available": False, "loraSupported": True, "derivedLocal": True, "recommendedOrder": 4,
            "unavailableReason": "公式FP32資産とMLX FP16の導入後に選択できます。追加ダウンロードは不要です。"}
