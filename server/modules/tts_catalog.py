from __future__ import annotations

import re
import platform
import sys
from datetime import date
from pathlib import Path
from typing import Any

from server.modules.tts_mlx_fp32 import fp32_catalog_variant
from server.modules.tts_large_assets import large_fp32_assets
from server.modules.tts_mlx_variants import MLX_VARIANTS_BY_BASE_REPO, MLX_RUNTIMES, mlx_runtime
from server.modules.tts_windows_quantized_variants import QUANTIZED_REPOS, windows_quantized_variants

ENGINE_REPO = "Aratako/Irodori-TTS"
ENGINE_COMMIT = "8224dafb46d0aba89209a8f905f1cb7e3299d9c1"
MEANFLOW_ENGINE_COMMIT = "89f9d8fbd4d51ea019867ee1197725ede1df13c5"
LARGE_MODEL_REPO = "Aratako/Irodori-TTS-v4-Large"
LARGE_MODEL_REVISION = "2e0c55428ce97268a507f1feeb2478f8d9148e8b"
MODEL_REPO = "Aratako/Irodori-TTS-v4.1-Small"
MODEL_REVISION = "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"
MEANFLOW_MODEL_REPO = "Aratako/Irodori-TTS-v4.1-Small-MF"
MEANFLOW_MODEL_REVISION = "ccc78f5d480b6e51b69b2d5042a14c4da04fea6e"
ANIME_MODEL_REPO = "phasefield-audio/Irodori-TTS-v4.1-Anime"
ANIME_MODEL_REVISION = "6b259f5baa5e236b3d14cbd1f8555ca87d92b530"
ANIME_NOTICE = "phasefield-audio氏制作の第三者ファインチューニングモデルです。Aratako氏による制作・公式配布ではありません。"
ANIME_DOWNLOAD_FILES = (
    "model.safetensors",
    "tokenizer/tokenizer.json",
    "tokenizer/tokenizer_config.json",
    "README.md",
)
CODEC_REVISION = "47376ee24834d7a05a48ebabfe3cde29b3c5e214"
ENGINE_ID = f"{ENGINE_REPO}@{ENGINE_COMMIT}"
MEANFLOW_ENGINE_ID = f"{ENGINE_REPO}@{MEANFLOW_ENGINE_COMMIT}"
MODEL_ID = f"{MODEL_REPO}@{MODEL_REVISION}"
PYTORCH_FP32_VARIANT_ID = "pytorch-fp32"
MLX_FP16_VARIANT_ID = "mlx-fp16"
MLX_8BIT_VARIANT_ID = "mlx-8bit"
V4_SMALL_REVISION = "4c92c7ee2bb15c19a97cf4e86d24fd6bf33b0135"
V3_VOICEDESIGN_REVISION = "e863a3a93e652e09afeff3e84823a206a0a60314"
V3_BASE_REVISION = "236c1e56591279fc24e3c1bf6609fc06e48dde28"
# GPU memory a model needs before Windows startup preparation may load it beside other work.
# Measured process peak on RTX 4070 Ti (docs/validation/windows-vram-requirements-2026-11-24.md),
# plus 0.8 GiB for the SCENA CUDA adapter on the engine that uses it, rounded up to 0.5 GiB.
# A quantized distribution shares one revision across its formats; W8A16 used the most.
# Large FP32 alone exceeds a 12 GB GPU, so it stays unverified and never preloads.
_GIB = 1024 ** 3
VERIFIED_VRAM_REQUIREMENTS = {
    MODEL_REVISION: 8 * _GIB, V4_SMALL_REVISION: 8 * _GIB, ANIME_MODEL_REVISION: 8 * _GIB,
    QUANTIZED_REPOS[MODEL_REPO]["revision"]: int(5.5 * _GIB),
    QUANTIZED_REPOS["Aratako/Irodori-TTS-v4-Small"]["revision"]: int(5.5 * _GIB),
    QUANTIZED_REPOS[LARGE_MODEL_REPO]["revision"]: int(9.5 * _GIB),
    MEANFLOW_MODEL_REVISION: int(6.5 * _GIB),
    V3_VOICEDESIGN_REVISION: int(7.5 * _GIB), V3_BASE_REVISION: int(6.5 * _GIB),
}

MODEL_RELEASE_METADATA = {
    LARGE_MODEL_REPO: ("Aratako", "2026-09-27"),
    "Aratako/Irodori-TTS-v4.1-Small": ("Aratako", "2026-08-11"),
    MEANFLOW_MODEL_REPO: ("Aratako", "2026-09-12"),
    ANIME_MODEL_REPO: ("phasefield-audio", "2026-09-04"),
    "Aratako/Irodori-TTS-v4-Small": ("Aratako", "2026-08-01"),
    "Aratako/Irodori-TTS-600M-v3-VoiceDesign": ("Aratako", "2026-05-31"),
    "Aratako/Irodori-TTS-500M-v3": ("Aratako", "2026-05-12"),
}

MODEL_DESCRIPTIONS = {
    LARGE_MODEL_REPO: ("約33億パラメータの大規模モデル", "T5Gemma 2を採用した大規模モデルです。Smallより多くのメモリとストレージを使用します。"),
    "Aratako/Irodori-TTS-v4.1-Small": ("品質を重視した標準モデル", "音声品質を重視した標準モデルです。どれを選ぶか迷った場合におすすめです。"),
    MEANFLOW_MODEL_REPO: ("生成速度を重視した高速モデル", "生成速度を重視した高速モデルです。待ち時間を短くしたい場合に適しています。"),
    ANIME_MODEL_REPO: ("アニメ調の音声表現に特化した第三者モデル", "アニメ調の音声データで追加学習された第三者モデルです。"),
}

MODEL_SPECS = (
    ("Aratako/Irodori-TTS-v4.1-Small", "Irodori-TTS v4.1 Small", "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b", "c85de88c01700cb53538e706f128ebcb1b8513ad21d7d0e75f58bc82cdbf89f6", 3064295596, "v4.1", False, 1, True, True, True, True, ENGINE_ID, "rf_velocity", None, True, True),
    (MEANFLOW_MODEL_REPO, "Irodori-TTS v4.1 Small MF", MEANFLOW_MODEL_REVISION, "a3f204b3ee06058f4e639a1af38408e7e3af5b6c75176897ecb8bfaaebb4fd54", 3093131788, "v4.1-mf", False, 2, True, True, True, True, MEANFLOW_ENGINE_ID, "meanflow", 4, False, False),
    (ANIME_MODEL_REPO, "Irodori-TTS v4.1 Small Anime", ANIME_MODEL_REVISION, "5630aa0a661930ff678a1d1f1893876e24520f4776d4fcc25ca54e6ab9f41f37", 3064295596, "v4.1", False, 3, True, True, True, True, ENGINE_ID, "rf_velocity", None, True, True),
    ("Aratako/Irodori-TTS-v4-Small", "Irodori-TTS v4 Small", V4_SMALL_REVISION, "5863c986345d9f6d20b7d8748fee1af02079c5161cf0c9e52557da0a0c378593", 3064295596, "v4", True, 4, True, True, True, True, ENGINE_ID, "rf_velocity", None, True, True),
    ("Aratako/Irodori-TTS-600M-v3-VoiceDesign", "Irodori-TTS v3 VoiceDesign", V3_VOICEDESIGN_REVISION, "93c1f8356857ab4297073f452d01c29015e0db5c83c62109800f8566900f4497", 2468332708, "v3", True, 5, True, True, True, True, ENGINE_ID, "rf_velocity", None, True, True),
    ("Aratako/Irodori-TTS-500M-v3", "Irodori-TTS v3 Base", V3_BASE_REVISION, "c4b8e7e982697664f829b7fb6bea307a25bd7ee013ad0d6114efc3e326acbd54", 2048269748, "v3", True, 6, True, False, False, True, ENGINE_ID, "rf_velocity", None, True, True),
    (LARGE_MODEL_REPO, "Irodori-TTS v4 Large", LARGE_MODEL_REVISION, "0f3de3cdcb8cb82ac2d0089f2c051ab99e12eb7270625d06e3d1d303bad9e63c", 13152893348, "v4", False, 7, True, True, True, True, MEANFLOW_ENGINE_ID, "rf_velocity", None, True, True),
)


def tts_catalog() -> dict[str, Any]:
    """Return the bundled, verified-input fallback catalogue."""
    catalog = {
        "version": 2,
        "verified": True,
        "source": "bundled-fallback",
        "engines": [{
            "id": engine_id, "displayName": display_name,
            "repo": ENGINE_REPO, "commit": commit_value, "pythonVersion": "3.10",
            "archiveUrl": f"https://github.com/{ENGINE_REPO}/archive/{commit_value}.tar.gz",
            "archiveSha256": archive_sha,
            "dependencyLockSha256": "8175adbb9ad7ae77d1f048344343a63876e57c333b659314bcc054230b5b3e6c",
            "supportedModelIds": [f"{spec[0]}@{spec[2]}" for spec in MODEL_SPECS if spec[12] == engine_id],
            "optimizationProfile": optimization_profile,
            "minimumScenaVersion": "0.1.0", "installable": True,
            "license": "MIT", "licenseUrl": f"https://github.com/{ENGINE_REPO}/blob/{commit_value}/LICENSE",
        } for engine_id, display_name, commit_value, archive_sha, optimization_profile in (
            (ENGINE_ID, "Irodori-TTS v4 対応版", ENGINE_COMMIT, "38ab365dae85483713196125438068a51b831451817a2e7447e04ec2bcde6f9b", "mps-fp32-v1"),
            (MEANFLOW_ENGINE_ID, "Irodori-TTS MeanFlow / Large 対応版", MEANFLOW_ENGINE_COMMIT, "5125a538d00fedce4bd75dc20115e4d042d310cadfbffbbeeb257645f06671f0", "upstream-meanflow"),
        )],
        "models": [{
            "id": f"{repo}@{revision}", "displayName": display_name,
            "repo": repo, "revision": revision, "format": "safetensors",
            "precision": "FP32", "sizeBytes": size_bytes, "supportedEngineIds": [engine_id],
            "modelSha256": model_sha,
            "codecRepo": "Aratako/Semantic-DACVAE-Japanese-32dim",
            "codecSha256": "db120339c5ee7eca1912cdf29bc612b947a0808e69c3cebfb4936b45a762c1d5",
            "codecRevision": CODEC_REVISION, "license": "Gemma" if repo == LARGE_MODEL_REPO else "MIT",
            "modelCardUrl": f"https://huggingface.co/{repo}", "installable": True,
            "author": MODEL_RELEASE_METADATA[repo][0],
            "releasedAt": MODEL_RELEASE_METADATA[repo][1],
            **({"tagline": MODEL_DESCRIPTIONS[repo][0], "description": MODEL_DESCRIPTIONS[repo][1]} if repo in MODEL_DESCRIPTIONS else {}),
            "generation": generation, "referenceVoice": reference_voice, "voiceDesign": voice_design,
            "combinedReferenceCaption": combined,
            "legacy": legacy, "recommendedOrder": recommended_order,
            "flowParameterization": flow_parameterization, "fixedSteps": fixed_steps,
            "supportsRuntimeCfg": supports_runtime_cfg, "supportsQualityPresets": supports_quality_presets,
            "tokenizerRepo": repo if generation.startswith("v4") else "llm-jp/llm-jp-3-150m",
            "tokenizerRevision": revision if generation.startswith("v4") else "b112feef602fff752e4dac4c30af6a2c2fa41c7a",
            "tokenizerSha256": None if generation.startswith("v4") else "955dc1fa623fab38cc92a3f4ee172423ae6d73201c4207569bfdf5626bc733f0",
            "variants": _model_variants(repo, revision, model_sha, size_bytes, engine_id),
            **({"notice": "Gemma利用条件および禁止用途ポリシーが適用されます。", **large_fp32_assets(model_sha)} if repo == LARGE_MODEL_REPO else {}),
            **({
                "publisher": "phasefield-audio",
                "provenance": "third-party-finetune",
                "notice": ANIME_NOTICE,
                "downloadFiles": list(ANIME_DOWNLOAD_FILES),
            } if repo == ANIME_MODEL_REPO else {"provenance": "upstream"}),
        } for repo, display_name, revision, model_sha, size_bytes, generation, legacy, recommended_order,
              reference_voice, voice_design, combined, duration_prediction, engine_id, flow_parameterization,
              fixed_steps, supports_runtime_cfg, supports_quality_presets in MODEL_SPECS],
    }
    return validate_tts_catalog(catalog, signature_verified=True)


def _model_variants(repo: str, revision: str, model_sha: str, size_bytes: int, engine_id: str) -> list[dict[str, Any]]:
    variants = [{
        "id": PYTORCH_FP32_VARIANT_ID, "displayName": "FP32", "precision": "FP32",
        "backend": "pytorch", "supportedOs": ["macos", "windows"],
        "supportedCpu": ["arm64", "x86_64"], "repo": repo, "revision": revision,
        "sizeBytes": size_bytes, "modelSha256": model_sha,
        "downloadFiles": list(ANIME_DOWNLOAD_FILES) if repo == ANIME_MODEL_REPO else None,
        "runtimeProfile": "pytorch-fp32", "supportedEngineIds": [engine_id],
        "computePrecision": "fp32", "checkpointFile": "model.safetensors",
        "visible": True, "available": True, "recommendedOrder": 2,
    }]
    if repo == LARGE_MODEL_REPO:
        variants[0].update(large_fp32_assets(model_sha))
    mlx_available = sys.platform == "darwin" and platform.machine().lower() in {"arm64", "aarch64"}
    for mlx_spec in MLX_VARIANTS_BY_BASE_REPO.get(repo, ()):
        variants.append({
            **mlx_spec,
            "loraSupported": repo == MODEL_REPO and revision == MODEL_REVISION and mlx_spec["id"] == MLX_FP16_VARIANT_ID,
            "backend": "mlx", "supportedOs": ["macos"], "supportedCpu": ["arm64"],
            "runtimeProfile": f"mlx-audio-{mlx_runtime(mlx_spec)['version']}-{mlx_spec['precision'].lower()}",
            "runtimePackage": mlx_runtime(mlx_spec)["package"], "supportedEngineIds": [],
            "available": mlx_available,
            "visible": sys.platform == "darwin",
            "unavailableReason": "Apple Silicon搭載macOSで利用できます。",
            "recommendedOrder": 1 if mlx_spec["id"] in {MLX_FP16_VARIANT_ID, "mlx-bf16"} else 3,
        })
    if local_fp32 := fp32_catalog_variant(repo, revision, model_sha):
        variants.append(local_fp32)
    windows_variants = windows_quantized_variants(repo)
    for variant in windows_variants:
        variant["supportedEngineIds"] = [engine_id]
    if sys.platform == "win32":
        for index, variant in enumerate(windows_variants):
            # FP32 is order 2: it is recommended wherever W8A16 is not preferred.
            variant["recommendedOrder"] = 1 if variant.get("preferred") else index + 3
    variants.extend(windows_variants)
    return sorted(variants, key=lambda variant: variant["recommendedOrder"]) if sys.platform == "win32" else variants


def _validate_sampling_capabilities(item: dict[str, Any]) -> None:
    if item["flowParameterization"] not in {"rf_velocity", "meanflow"}:
        raise ValueError("モデルのサンプリング方式が不正です。")
    if item["flowParameterization"] == "meanflow" and (item["fixedSteps"] != 4 or item["supportsRuntimeCfg"] or item["supportsQualityPresets"]):
        raise ValueError("MeanFlowモデルの固定サンプリング能力が不正です。")


def _validate_release_metadata(item: dict[str, Any]) -> None:
    if not isinstance(item.get("author"), str) or not item["author"].strip():
        raise ValueError("モデルの作者情報が不正です。")
    try:
        date.fromisoformat(str(item.get("releasedAt", "")))
    except ValueError as error:
        raise ValueError("モデルのリリース日が不正です。") from error


def _validate_variants(variants: Any, commit: re.Pattern[str], sha: re.Pattern[str]) -> None:
    if not isinstance(variants, list) or not variants:
        raise ValueError("モデルのバリアント情報が不足しています。")
    variant_ids: set[str] = set()
    for variant in variants:
        if variant.get("id") in variant_ids or variant.get("backend") not in {"pytorch", "mlx"}:
            raise ValueError("モデルバリアントのIDまたはbackendが不正です。")
        variant_ids.add(str(variant.get("id")))
        if not commit.fullmatch(str(variant.get("revision", ""))) or not sha.fullmatch(str(variant.get("modelSha256", ""))):
            raise ValueError("モデルバリアントのrevisionまたはSHA-256が不正です。")
        if variant.get("backend") == "mlx" and variant.get("runtimePackage") not in {runtime["package"] for runtime in MLX_RUNTIMES.values()}:
            raise ValueError("MLX runtimeは完全固定する必要があります。")
        checkpoint = variant.get("checkpointFile", "model.safetensors")
        if Path(str(checkpoint)).is_absolute() or ".." in Path(str(checkpoint)).parts:
            raise ValueError("モデルcheckpointの相対パスが不正です。")
        if variant.get("computePrecision", "fp32") not in {"fp32", "bf16"}:
            raise ValueError("モデル計算精度が不正です。")
        artifacts = variant.get("artifactFiles", [])
        if artifacts and (
            {entry.get("path") for entry in artifacts} != set(variant.get("downloadFiles", []))
            or any(not sha.fullmatch(str(entry.get("sha256", ""))) for entry in artifacts)
        ):
            raise ValueError("モデルバリアントの許可ファイルSHA-256が不正です。")


def validate_tts_catalog(catalog: dict[str, Any], *, signature_verified: bool) -> dict[str, Any]:
    if not signature_verified:
        raise ValueError("互換カタログの署名を検証できません。")
    engines, models = catalog.get("engines"), catalog.get("models")
    if not isinstance(engines, list) or not isinstance(models, list):
        raise ValueError("互換カタログの形式が不正です。")
    sha = re.compile(r"^[0-9a-f]{64}$")
    commit = re.compile(r"^[0-9a-f]{40}$")
    engine_ids = {item.get("id") for item in engines}
    for item in engines:
        if item.get("repo") != ENGINE_REPO or not commit.fullmatch(str(item.get("commit", ""))):
            raise ValueError("許可されていないエンジン配布元またはcommitです。")
        if not str(item.get("archiveUrl", "")).startswith(f"https://github.com/{ENGINE_REPO}/archive/"):
            raise ValueError("許可されていないエンジン配布URLです。")
        if not sha.fullmatch(str(item.get("archiveSha256", ""))) or not sha.fullmatch(str(item.get("dependencyLockSha256", ""))):
            raise ValueError("エンジン資産のSHA-256が不正です。")
        if _version_tuple(str(item.get("minimumScenaVersion", "0"))) > _version_tuple("0.1.0"):
            item["installable"] = False
            item["unavailableReason"] = f"SCENA {item['minimumScenaVersion']} 以降が必要です。"
    for item in models:
        if item.get("repo") not in {spec[0] for spec in MODEL_SPECS} or item.get("codecRepo") != "Aratako/Semantic-DACVAE-Japanese-32dim":
            raise ValueError("許可されていないモデル配布元です。")
        if not commit.fullmatch(str(item.get("revision", ""))) or not commit.fullmatch(str(item.get("codecRevision", ""))):
            raise ValueError("モデルrevisionが不正です。")
        if not sha.fullmatch(str(item.get("modelSha256", ""))) or not sha.fullmatch(str(item.get("codecSha256", ""))):
            raise ValueError("モデル資産のSHA-256が不正です。")
        if not set(item.get("supportedEngineIds", [])).issubset(engine_ids):
            raise ValueError("モデルの互換エンジンがカタログにありません。")
        required_capabilities = ("generation", "referenceVoice", "voiceDesign", "combinedReferenceCaption", "legacy", "recommendedOrder", "flowParameterization", "fixedSteps", "supportsRuntimeCfg", "supportsQualityPresets")
        if any(key not in item for key in required_capabilities):
            raise ValueError("モデルの能力情報が不足しています。")
        _validate_variants(item.get("variants"), commit, sha)
        _validate_sampling_capabilities(item)
        _validate_release_metadata(item)
        download_files = item.get("downloadFiles")
        if download_files is not None and (
            not isinstance(download_files, list)
            or not download_files
            or any(not isinstance(path, str) or Path(path).is_absolute() or ".." in Path(path).parts for path in download_files)
        ):
            raise ValueError("モデル取得対象の相対パスが不正です。")
    return catalog


def _version_tuple(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(".") if part.isdigit())
