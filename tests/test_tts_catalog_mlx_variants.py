import scena_test_isolation  # noqa: F401
import unittest

from server.modules.tts_catalog import tts_catalog


EXPECTED_MLX_REPOS = {
    "Aratako/Irodori-TTS-v4.1-Small": (
        "mlx-community/Irodori-TTS-v4.1-Small-fp16",
        "mlx-community/Irodori-TTS-v4.1-Small-8bit",
    ),
    "Aratako/Irodori-TTS-v4.1-Small-MF": (
        "mlx-community/Irodori-TTS-v4.1-Small-MF-fp16",
        "mlx-community/Irodori-TTS-v4.1-Small-MF-8bit",
    ),
    "Aratako/Irodori-TTS-v4-Small": (
        "mlx-community/Irodori-TTS-v4-Small-fp16",
        "mlx-community/Irodori-TTS-v4-Small-8bit",
    ),
    "Aratako/Irodori-TTS-600M-v3-VoiceDesign": (
        "mlx-community/Irodori-TTS-600M-v3-VoiceDesign-fp16",
        "mlx-community/Irodori-TTS-600M-v3-VoiceDesign-8bit",
    ),
    "Aratako/Irodori-TTS-500M-v3": (
        "mlx-community/Irodori-TTS-500M-v3-fp16",
        "mlx-community/Irodori-TTS-500M-v3-8bit",
    ),
}


class TtsCatalogMlxVariantTests(unittest.TestCase):
    def setUp(self) -> None:
        self.models = {model["repo"]: model for model in tts_catalog()["models"]}

    def test_official_models_expose_pinned_mlx_variants(self) -> None:
        for base_repo, expected_repos in EXPECTED_MLX_REPOS.items():
            variants = [variant for variant in self.models[base_repo]["variants"] if not variant.get("derivedLocal") and (variant["backend"] == "mlx" or variant["id"] == "pytorch-fp32")]
            self.assertEqual([variant["id"] for variant in variants], ["pytorch-fp32", "mlx-fp16", "mlx-8bit"])
            self.assertEqual(tuple(variant["repo"] for variant in variants[1:]), expected_repos)
            for variant in variants[1:]:
                self.assertEqual(len(variant["revision"]), 40)
                self.assertEqual(variant["runtimePackage"], "mlx-audio==0.5.0")
                self.assertEqual(variant["supportedOs"], ["macos"])
                self.assertEqual(variant["supportedCpu"], ["arm64"])
                self.assertEqual(set(variant["downloadFiles"]), {entry["path"] for entry in variant["artifactFiles"]})
                model_hash = next(entry["sha256"] for entry in variant["artifactFiles"] if entry["path"] == "model.safetensors")
                self.assertEqual(model_hash, variant["modelSha256"])

    def test_v3_variants_follow_their_tokenizer_free_distribution(self) -> None:
        for base_repo in ("Aratako/Irodori-TTS-600M-v3-VoiceDesign", "Aratako/Irodori-TTS-500M-v3"):
            for variant in self.models[base_repo]["variants"][1:]:
                self.assertFalse(any(path.startswith("tokenizer/") for path in variant["downloadFiles"]))

    def test_anime_model_has_no_mlx_variants(self) -> None:
        anime = self.models["phasefield-audio/Irodori-TTS-v4.1-Anime"]

        self.assertEqual(
            [(variant["id"], variant["precision"], variant["backend"]) for variant in anime["variants"] if variant.get("visible", True)],
            [("pytorch-fp32", "FP32", "pytorch")],
        )
