from __future__ import annotations

import ctypes
import sys
from ctypes.util import find_library
from typing import Any

from server.modules.tts_large_assets import LARGE_SHARED_ARTIFACTS, LARGE_SHARED_BYTES, LARGE_QUANTIZED_REPO, LARGE_QUANTIZED_REVISION

TOKENIZER_FILES = ("tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json")
QUANTIZED_REPOS = {
    "Aratako/Irodori-TTS-v4-Large": {
        "repo": LARGE_QUANTIZED_REPO,
        "revision": LARGE_QUANTIZED_REVISION,
        "readmeSha256": "36da2c566b2b54e97c6611f33925207877181935455445e3e27df860fa802407",
        "tokenizerSha256": (
            "f5b325224482ec441ec5fbe2a5ac08c3758e0f9605f6e54368e31f736fcfb01d",
            "1007769ea58b3c60a23a2ec21d99625f3433a18913492b9a7ea525759e312713",
        ),
        "models": {
            "float8-dynamic": (3836861578, "abad6e4fe79a94f7e3308d30a2ba3ba13ea207ab1511baa5e21f6f13955d06dd"),
            "float8-weight-only": (3842708698, "c85bad9757c4c617dbaf959f75d3b1a974bf5463eeee8a748f2f2ca92eef55c2"),
            "int4-weight-only": (2955004714, "5b8b9e2557f6f7f1a3df8dff1cc41d5ea95a8946729f4f4fd45ade5a9cb08a28"),
            "int8-dynamic": (3839702314, "816dc0007de8d5658358db4c6d2ee0439a541d46ea2abd800da89a00bd23916b"),
            "int8-weight-only": (3839580074, "b044816d341ae0f56137241d6d9821fe563b63412b693e6fc411d051116eb83a"),
        },
    },
    "Aratako/Irodori-TTS-v4.1-Small": {
        "repo": "Aratako/Irodori-TTS-v4.1-Small-Quantized", "revision": "ef04e6c3ba56138ae23e86a2eabc004f76990e37",
        "readmeSha256": "c9b36971d2cc6a93f762bb2dfda2c0484ae051031bb87e378d2f2b20e3f9286f",
        "tokenizerSha256": ("6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
        "models": {
            "int8-weight-only": (914316834, "1fb6394b52c11329fd19d6c6f388a1e224721752a32aad906cae8653f5b25dcc"),
            "int8-dynamic": (914381258, "2bd171194a26e366da8c61a7229fa0dd9874465b7e66035c89ed22bd68459dda"),
            "int4-weight-only": (852031658, "0ea9556d0aceaca3aafe904054bcdec357707fccb9c19c38784fc469bd6c03a7"),
            "float8-weight-only": (915532914, "220729e659be9c9e6def022ed9f12ac0cb883b52bc03049a5750dfd7faf68cdf"),
            "float8-dynamic": (950087258, "d607411fac826cefbb84e9183dca8fae0c72e5c6946806e09e13a5c389ac90cb"),
        },
    },
    "Aratako/Irodori-TTS-v4-Small": {
        "repo": "Aratako/Irodori-TTS-v4-Small-Quantized", "revision": "4a5a4d68c5a73d2742fbdb0ce679522f8c7fbdab",
        "readmeSha256": "6cc11b710eefed97f1f6990fec35a23b9f13ed971ce234869c67d861c27c313f",
        "tokenizerSha256": ("6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
        "models": {
            "int8-weight-only": (914316834, "1379d023c7248916fe6c105e18bcaa18d31a7ba5dead3bde26b14b2a8925de33"),
            "int8-dynamic": (914381258, "11f8846cc0e255e5897586e0b5b0b0a39c8057e197072109b2b3e65068653093"),
            "int4-weight-only": (852031658, "b5368c99488b8999c8bf28e2f8288fbf0d0ce3dec8024a2dcf447a0965ad2e2d"),
            "float8-weight-only": (915532914, "aa5dff2624376490ce7f9b26283b59eb5f4b065cc33de1ddb75c90f29457003d"),
            "float8-dynamic": (950087258, "c5a7281c227bad6ccbb77cec61d80c1fb3e220db99eb7f5154fef4197e6d1564"),
        },
    },
    "phasefield-audio/Irodori-TTS-v4.1-Anime": {
        "repo": "phasefield-audio/Irodori-TTS-v4.1-Anime", "revision": "6b259f5baa5e236b3d14cbd1f8555ca87d92b530",
        "readmeSha256": "28bd916a1312c4da901cfaf5bb4476cad5b9b21595e6514b2326707e8c82d773",
        "tokenizerSha256": ("6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
        "models": {
            "int8-weight-only": (914316834, "8933f931ef2479364748a048c6613e690215afca175b06e4adfb5345eece9b0c"),
            "int8-dynamic": (914381258, "7bc3f8ebc6234070bf0f7a2f1f91fc784b53f36760b9bc1b352e4c350e4d839d"),
            "int4-weight-only": (852031658, "db9fef77ef0a5b156e37eb7deed1fa9f4672a583590902e6600f42a915e43a3a"),
            "float8-weight-only": (915532914, "1101d52a407ac911cd2ccc7e6ca248177c0ed83b85352be0fd262924e3aaa565"),
            "float8-dynamic": (950087258, "473270e6257ebc20544bcd6bed46cf93d466530a5afa6d5409fca6fd156e4cb5"),
        },
    },
}
VARIANT_SPECS = (
    ("pytorch-w8a16", "W8A16", "int8-weight-only", 0),
    ("pytorch-w8a8", "W8A8", "int8-dynamic", 0),
    ("pytorch-w4a16", "W4A16", "int4-weight-only", 80),
    ("pytorch-fp8-weight-only", "FP8/BF16", "float8-weight-only", 89),
    ("pytorch-fp8-dynamic", "FP8 Dynamic", "float8-dynamic", 89),
)


# The pinned cu128 PyTorch has no Maxwell or Pascal kernels; BF16 is native from Ampere.
CUDA_MINIMUM_CAPABILITY = 70
W8A16_RECOMMENDED_CAPABILITY = 80


def cuda_compute_capability() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        cuda = ctypes.WinDLL(find_library("nvcuda") or "nvcuda.dll")
        count, device, major, minor = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        if cuda.cuInit(0) != 0 or cuda.cuDeviceGetCount(ctypes.byref(count)) != 0 or count.value < 1:
            return None
        if cuda.cuDeviceGet(ctypes.byref(device), 0) != 0 or cuda.cuDeviceComputeCapability(ctypes.byref(major), ctypes.byref(minor), device) != 0:
            return None
        return major.value, minor.value
    except (AttributeError, OSError):
        return None


def windows_quantized_variants(base_repo: str, capability: tuple[int, int] | None = None) -> list[dict[str, Any]]:
    distribution = QUANTIZED_REPOS.get(base_repo)
    if not distribution:
        return []
    detected = cuda_compute_capability() if capability is None else capability
    capability_value = detected[0] * 10 + detected[1] if detected else None
    result = []
    for order, (variant_id, label, quantization, minimum) in enumerate(VARIANT_SPECS, start=1):
        size, model_sha = distribution["models"][quantization]
        checkpoint = f"{quantization}/model.safetensors"
        required = max(minimum, CUDA_MINIMUM_CAPABILITY)
        available = capability_value is not None and capability_value >= required
        reason = "NVIDIA CUDA GPUの互換性を確認できませんでした。" if capability_value is None else None
        if capability_value is not None and capability_value < CUDA_MINIMUM_CAPABILITY:
            reason = "このGPUはCUDA版の推論に対応していません（Compute Capability 7.0以上が必要です）。"
        elif capability_value is not None and capability_value < required:
            reason = f"Compute Capability {required // 10}.{required % 10}以上が必要です。"
        artifacts = [{"path": checkpoint, "sha256": model_sha}, {"path": "README.md", "sha256": distribution["readmeSha256"]}]
        artifacts.extend({"path": path, "sha256": sha} for path, sha in zip(TOKENIZER_FILES, distribution["tokenizerSha256"], strict=True))
        shared_bytes = 6723415
        if base_repo == "Aratako/Irodori-TTS-v4-Large":
            artifacts = artifacts[:2] + list(LARGE_SHARED_ARTIFACTS)
            shared_bytes = LARGE_SHARED_BYTES + 4628
        result.append({
            "id": variant_id, "displayName": label, "precision": label, "backend": "pytorch",
            "repo": distribution["repo"], "revision": distribution["revision"], "sizeBytes": size + shared_bytes,
            "modelSha256": model_sha, "downloadFiles": [entry["path"] for entry in artifacts], "artifactFiles": artifacts,
            "checkpointFile": checkpoint, "computePrecision": "bf16", "quantization": quantization,
            "supportedOs": ["windows"], "supportedCpu": ["x86_64"], "runtimeProfile": f"pytorch-torchao-{quantization}",
            "visible": sys.platform == "win32", "available": available, "unavailableReason": reason, "recommendedOrder": order,
            "preferred": variant_id == "pytorch-w8a16" and capability_value is not None and capability_value >= W8A16_RECOMMENDED_CAPABILITY,
        })
    return result
