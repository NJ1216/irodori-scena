from __future__ import annotations

from typing import Any

from server.modules.tts_large_assets import LARGE_SHARED_ARTIFACTS


def _variant(
    precision: str,
    repo: str,
    revision: str,
    size_bytes: int,
    model_sha256: str,
    files: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    variant_id = {"FP16": "mlx-fp16", "BF16": "mlx-bf16", "8bit": "mlx-8bit"}[precision]
    return {
        "id": variant_id,
        "displayName": precision,
        "precision": precision,
        "repo": repo,
        "revision": revision,
        "sizeBytes": size_bytes,
        "modelSha256": model_sha256,
        "downloadFiles": [path for path, _sha256 in files],
        "artifactFiles": [{"path": path, "sha256": sha256} for path, sha256 in files],
    }


_V41_FILES = (
    ("README.md", "fe73fe9bd25bd749d5267801621202a58d8e76a079d48ff8b5b2d404c8a7d3d2"),
    ("config.json", "1fd3b64b681229e5226a873de625589aa0fffc865c0404389b92e917c8c6708b"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("model.safetensors", "99e022893ed27353aea6fca3897ee94c62bbaa568d705d230ee9b69f80a3a3bf"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("tokenizer/tokenizer.json", "6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d"),
    ("tokenizer/tokenizer_config.json", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
)
_V41_8BIT_FILES = (
    ("README.md", "462db03669322f7f6a2997422f5250c166e8b023051279b7f22eb421bc8570a1"),
    ("config.json", "fe37faab132a418f259cf97fda047da19dd8abe60e458e3b634edc790bb545a1"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("model.safetensors", "b24b776dda4a03c12174896f0e00412b9d3521abca11fadab32ea715144d3ab0"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("tokenizer/tokenizer.json", "6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d"),
    ("tokenizer/tokenizer_config.json", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
)

_V41_MF_FP16_FILES = (
    ("README.md", "93bda001b8762081b4d1d55b57c2dc924f297b71602e568cfcddea2d8672293b"),
    ("config.json", "d181702b6c6977cd4d5cfa23462abbd26b2122e3d4306971bbec563073f7d2ce"),
    ("dacvae/config.json", "86aeeace595882a046d50c010971d79ed2e6bf1215a6b51b18e99b50b3fadeac"),
    ("dacvae/model.safetensors", "7366646af3d250ec0162c2b2717a64f7dbd5b8bfaebbf9ed69ad79db4944b8b9"),
    ("model.safetensors", "19bd887050cb3a6e799f4043aa2e20c11c1783f3af04e6c4d8ee0f172d24e483"),
    ("tokenizer/tokenizer.json", "6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d"),
    ("tokenizer/tokenizer_config.json", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
)
_V41_MF_8BIT_FILES = (
    ("README.md", "223879d16b989de76debc4602b6568851cf8eb3e8f38bebbd70f26ac9b3ff084"),
    ("config.json", "f5ed03bb6c2e166ecc17e214fbc7c34b553de65bf0468413b41141ab240d2281"),
    ("dacvae/config.json", "86aeeace595882a046d50c010971d79ed2e6bf1215a6b51b18e99b50b3fadeac"),
    ("dacvae/model.safetensors", "7366646af3d250ec0162c2b2717a64f7dbd5b8bfaebbf9ed69ad79db4944b8b9"),
    ("model.safetensors", "0f399266214856bd7e90768bba033793053f28088ec0fdc8c3f5516342d8e9c7"),
    ("tokenizer/tokenizer.json", "6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d"),
    ("tokenizer/tokenizer_config.json", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
)

_V4_FP16_FILES = (
    ("README.md", "c2df44906c4c5e7d506fe135d2f9272df2c55cd78f8ad16cb279d2695b548741"),
    ("config.json", "162f6a564f3b4f22f8cf09e15375356fa211f9c25ee2fa01e9a965b8cc74c2de"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("model.safetensors", "1290649638f3962b5e7aa9f73424b1f726b932831afd2908a5e1aacf580c1521"),
    ("tokenizer/tokenizer.json", "6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d"),
    ("tokenizer/tokenizer_config.json", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
)
_V4_8BIT_FILES = (
    ("README.md", "c1fe5ff33a11e34d26565609c08ff210072853db914d3219c2186c9575e2687a"),
    ("config.json", "e6506b2a863a006671a1775559c594a2aba8e2a447c5e69d49fd6771e4f202b2"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("model.safetensors", "025b541079401fdde2646ff4c9e5a13d072444893c1698d7bbc79dca7e2d51e2"),
    ("tokenizer/tokenizer.json", "6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d"),
    ("tokenizer/tokenizer_config.json", "d229a271c64de1a7939d20d3665498e873fa91d5ee2edf135d73ec752cb9c9d3"),
)

_V3_VOICE_FP16_FILES = (
    ("README.md", "e6978c5683f01be3f4d84bf1e8efd2c31b811788042068339abf20b9798a3ca7"),
    ("config.json", "2e75a58f17618a3a337c15e8f455584c7ac94e59977f61c612d5ec327e5acad6"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("model.safetensors", "05dd9bf03df2bf6370584496e3763162cabd381fa6e4490a1688260232f75968"),
)
_V3_VOICE_8BIT_FILES = (
    ("README.md", "1d6c2454fc74e3ab72fd6217b909a6ea1c3a2abffe0add7c6ae933e1bc346872"),
    ("config.json", "a206234fbae5e247fbd50f4603697a27ad22e2699f43784f6ef65f1bfe71e731"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("model.safetensors", "f1061cfe2c3841ab933b75858e99ed98cf865942123f69e2338846bcf69f5868"),
)

_V3_BASE_FP16_FILES = (
    ("README.md", "28423c8f359ffd10a14d26a650e59ad99d23c034b9cc27c4e6d7f8b10b8bb056"),
    ("config.json", "8ddd3f8c1b337824b507c6807a52d571b9cb8b33a6d658205d36e646212d52fc"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("model.safetensors", "28a00a0b9c054fe14a481661df5be9865114cbac1c4414b14982cad53c152dc9"),
)
_V3_BASE_8BIT_FILES = (
    ("README.md", "06d9e33386613a3802cbedf2b8ac7cb4b50f15a1ee0e64690a8fcce653f06d96"),
    ("config.json", "33ac6f5a5d0695d25ed98d902ae4f44869b22224c98058382e7ae23cade06362"),
    ("dacvae/config.json", "8e01edaa4900841e36e1970bfced16470e8e4f4a5dc710f6ace1deefe731daf4"),
    ("dacvae/model.safetensors", "0bf3ff42e8101bd42ad082115ff0ea6867b6e994e64ab45f247bd50c49d0a0b9"),
    ("model.safetensors", "e33849dc6ba1b2e8c53d2620872ad5cc5e84e44e45bd5e077e7d42220ba9013a"),
)


# Large requires the T5Gemma2 loader from upstream PR #993.
LARGE_MLX_COMMIT = "de43d7c381e1f8fa108ac44bca707d9e613f7355"
LARGE_MLX_PACKAGE = (
    "mlx-audio @ https://codeload.github.com/yoshphys/mlx-audio/tar.gz/"
    + LARGE_MLX_COMMIT
    + "#sha256=26704f3527478efcde8629c743a63be0e4b3a2da3c60619cd29f8c9baa517455"
)
MLX_RUNTIMES = {
    "mlx-audio@0.5.0": {"version": "0.5.0", "package": "mlx-audio==0.5.0"},
    f"mlx-audio@{LARGE_MLX_COMMIT}": {"version": LARGE_MLX_COMMIT, "package": LARGE_MLX_PACKAGE},
}


def mlx_engine_id(variant: dict[str, Any]) -> str:
    return str(variant.get("runtimeEngineId") or "mlx-audio@0.5.0")


def mlx_runtime(variant: dict[str, Any]) -> dict[str, str]:
    return MLX_RUNTIMES[mlx_engine_id(variant)]

_V4_LARGE_BF16_FILES = (
    ('README.md', '0c4e5f51aa7bf005dbe2cdf5e7e83be2aef29cf63579b0f7b32574c7301e38b8'),
    ('config.json', 'e4169cc6a5721f74901170037e141ca1772e5e266bdc45cfe9dd42235fe87bb4'),
    ('dacvae/config.json', '86aeeace595882a046d50c010971d79ed2e6bf1215a6b51b18e99b50b3fadeac'),
    ('dacvae/model.safetensors', '7366646af3d250ec0162c2b2717a64f7dbd5b8bfaebbf9ed69ad79db4944b8b9'),
    ('model.safetensors', '8335bb9b379be078139c90ec67b9c4734883b200acc006cf55f6c61e0f26d42e'),
    ('tokenizer/tokenizer.json', 'f5b325224482ec441ec5fbe2a5ac08c3758e0f9605f6e54368e31f736fcfb01d'),
    ('tokenizer/tokenizer_config.json', '1007769ea58b3c60a23a2ec21d99625f3433a18913492b9a7ea525759e312713'),
)
_V4_LARGE_8BIT_FILES = (
    ('README.md', '206680b9e53caacf2a4a3bf9e88f27de5d7bc47bc7921bbd42a7c75c2a9f5641'),
    ('config.json', '46e02eb979da5bcdd80ea7c4f43e74e6d6a2be58c5106f8476dc5b8c9fd416ad'),
    ('dacvae/config.json', '86aeeace595882a046d50c010971d79ed2e6bf1215a6b51b18e99b50b3fadeac'),
    ('dacvae/model.safetensors', '7366646af3d250ec0162c2b2717a64f7dbd5b8bfaebbf9ed69ad79db4944b8b9'),
    ('model.safetensors', 'c1d7e5e85fc025e391cb816be29aad3e1e21dc894219026f4d6e33997988386b'),
    ('tokenizer/tokenizer.json', 'f5b325224482ec441ec5fbe2a5ac08c3758e0f9605f6e54368e31f736fcfb01d'),
    ('tokenizer/tokenizer_config.json', '1007769ea58b3c60a23a2ec21d99625f3433a18913492b9a7ea525759e312713'),
)


def _large_variant(precision: str, repo: str, revision: str, size_bytes: int, model_sha256: str, files: tuple[tuple[str, str], ...]) -> dict[str, Any]:
    terms = [entry for entry in LARGE_SHARED_ARTIFACTS if not entry["path"].startswith("tokenizer/")]
    variant = _variant(precision, repo, revision, size_bytes + 14490, model_sha256, files + tuple((entry["path"], entry["sha256"]) for entry in terms))
    return {**variant, "runtimeEngineId": f"mlx-audio@{LARGE_MLX_COMMIT}", "runtimePackage": LARGE_MLX_PACKAGE,
            "auxiliaryAssets": {"repo": "Aratako/Irodori-TTS-v4-Large", "revision": "2e0c55428ce97268a507f1feeb2478f8d9148e8b", "downloadFiles": [entry["path"] for entry in terms]}}

MLX_VARIANTS_BY_BASE_REPO = {
    "Aratako/Irodori-TTS-v4-Large": (
        _large_variant('BF16', 'mlx-community/Irodori-TTS-v4-Large-bf16', 'aaa931c7fc2092611cde1b9b8eecf4cf830bcb66', 7039437071, '8335bb9b379be078139c90ec67b9c4734883b200acc006cf55f6c61e0f26d42e', _V4_LARGE_BF16_FILES),
        _large_variant('8bit', 'mlx-community/Irodori-TTS-v4-Large-8bit', '100ccf6fd88ef5def71f6590f25452f9e2b0839b', 4470479606, 'c1d7e5e85fc025e391cb816be29aad3e1e21dc894219026f4d6e33997988386b', _V4_LARGE_8BIT_FILES),
    ),
    "Aratako/Irodori-TTS-v4.1-Small": (
        _variant("FP16", "mlx-community/Irodori-TTS-v4.1-Small-fp16", "8be8d91091380115f1ac77aeb6604ed588d05372", 1961695550, "99e022893ed27353aea6fca3897ee94c62bbaa568d705d230ee9b69f80a3a3bf", _V41_FILES),
        _variant("8bit", "mlx-community/Irodori-TTS-v4.1-Small-8bit", "c81956b675ce21422c305ef683fb2ac59d7faf6a", 1382100230, "b24b776dda4a03c12174896f0e00412b9d3521abca11fadab32ea715144d3ab0", _V41_8BIT_FILES),
    ),
    "Aratako/Irodori-TTS-v4.1-Small-MF": (
        _variant("FP16", "mlx-community/Irodori-TTS-v4.1-Small-MF-fp16", "db0263236d010d4beb6ca67c529f410a6f71d755", 1982838951, "19bd887050cb3a6e799f4043aa2e20c11c1783f3af04e6c4d8ee0f172d24e483", _V41_MF_FP16_FILES),
        _variant("8bit", "mlx-community/Irodori-TTS-v4.1-Small-MF-8bit", "76e6b18f9889e4cf50d90f7df91d9b6f56e23c3f", 1466864103, "0f399266214856bd7e90768bba033793053f28088ec0fdc8c3f5516342d8e9c7", _V41_MF_8BIT_FILES),
    ),
    "Aratako/Irodori-TTS-v4-Small": (
        _variant("FP16", "mlx-community/Irodori-TTS-v4-Small-fp16", "ed5ae496331288cb9aa6d5652aeec65cf7eb5265", 1968421349, "1290649638f3962b5e7aa9f73424b1f726b932831afd2908a5e1aacf580c1521", _V4_FP16_FILES),
        _variant("8bit", "mlx-community/Irodori-TTS-v4-Small-8bit", "74de56173cc1f2f1d9f741a42917d3d9b234596a", 1388826090, "025b541079401fdde2646ff4c9e5a13d072444893c1698d7bbc79dca7e2d51e2", _V4_8BIT_FILES),
    ),
    "Aratako/Irodori-TTS-600M-v3-VoiceDesign": (
        _variant("FP16", "mlx-community/Irodori-TTS-600M-v3-VoiceDesign-fp16", "544900a42d78532d6f74ef5b1303dbfc2be2da93", 1663723057, "05dd9bf03df2bf6370584496e3763162cabd381fa6e4490a1688260232f75968", _V3_VOICE_FP16_FILES),
        _variant("8bit", "mlx-community/Irodori-TTS-600M-v3-VoiceDesign-8bit", "0cff89f2d9dd47975b14666dda4855a67b53f231", 1258472415, "f1061cfe2c3841ab933b75858e99ed98cf865942123f69e2338846bcf69f5868", _V3_VOICE_8BIT_FILES),
    ),
    "Aratako/Irodori-TTS-500M-v3": (
        _variant("FP16", "mlx-community/Irodori-TTS-500M-v3-fp16", "989974578914517275a59aa02fc5701ba22d3862", 1453680459, "28a00a0b9c054fe14a481661df5be9865114cbac1c4414b14982cad53c152dc9", _V3_BASE_FP16_FILES),
        _variant("8bit", "mlx-community/Irodori-TTS-500M-v3-8bit", "43b5d5539d8f07da46c7cd58d9f0ebed50ec1cc9", 1092641579, "e33849dc6ba1b2e8c53d2620872ad5cc5e84e44e45bd5e077e7d42220ba9013a", _V3_BASE_8BIT_FILES),
    ),
}
