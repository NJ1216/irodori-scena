"""Pinned auxiliary files for the Gemma-derived v4-Large checkpoints."""

LARGE_SHARED_ARTIFACTS = (
    {"path": "tokenizer/tokenizer.json", "sha256": "f5b325224482ec441ec5fbe2a5ac08c3758e0f9605f6e54368e31f736fcfb01d"},
    {
        "path": "tokenizer/tokenizer_config.json",
        "sha256": "1007769ea58b3c60a23a2ec21d99625f3433a18913492b9a7ea525759e312713",
    },
    {"path": "NOTICE", "sha256": "cebce9f0aafbf8cbcaf2e5b5bbbce4c1fe36a8407acdf4865e2305441da05409"},
    {"path": "GEMMA_TERMS_OF_USE.md", "sha256": "3b65bc46747423037f7ca57af25b885a7be421948d7a81ca02b0cb038177ec3d"},
    {
        "path": "GEMMA_PROHIBITED_USE_POLICY.md",
        "sha256": "c9c86ddd3ac3a39236a72ee644421b07fa3b56e77c2a8e381818e5ec06dca1e2",
    },
)
LARGE_SHARED_BYTES = 33399679
LARGE_FP32_README_SHA256 = "8619ee154dfcc52430d8258328433e8dc47f12ed663eb0a216c5c7f0e2cd284d"

LARGE_QUANTIZED_REPO = "Aratako/Irodori-TTS-v4-Large-Quantized"
LARGE_QUANTIZED_REVISION = "bdef9592db4426bd1c99ccdf0cfc3a213223fb61"


def large_fp32_assets(model_sha: str) -> dict:
    artifacts = [
        {"path": "model.safetensors", "sha256": model_sha},
        {"path": "README.md", "sha256": LARGE_FP32_README_SHA256},
        *LARGE_SHARED_ARTIFACTS,
    ]
    return {"downloadFiles": [entry["path"] for entry in artifacts], "artifactFiles": artifacts}
