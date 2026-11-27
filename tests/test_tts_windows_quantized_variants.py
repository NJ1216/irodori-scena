from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import patch

from server.modules.tts_catalog import tts_catalog
from server.modules.tts_windows_quantized_variants import windows_quantized_variants


class WindowsQuantizedVariantTests(unittest.TestCase):
    def test_gpu_compatibility_matrix(self) -> None:
        expectations = {
            (6, 1): [False, False, False, False, False],
            (7, 5): [True, True, False, False, False],
            (8, 6): [True, True, True, False, False],
            (8, 9): [True, True, True, True, True],
        }
        for capability, available in expectations.items():
            with self.subTest(capability=capability):
                variants = windows_quantized_variants("Aratako/Irodori-TTS-v4.1-Small", capability)
                self.assertEqual([item["available"] for item in variants], available)

    def test_pre_volta_gpus_explain_that_cuda_is_unsupported(self) -> None:
        variants = windows_quantized_variants("Aratako/Irodori-TTS-v4.1-Small", (6, 1))
        self.assertTrue(all("7.0" in item["unavailableReason"] for item in variants))

    def test_w8a16_is_recommended_only_from_compute_capability_8_0(self) -> None:
        for capability, expected in [((7, 5), "FP32"), ((8, 0), "W8A16"), ((8, 9), "W8A16"), ((12, 0), "W8A16")]:
            with self.subTest(capability=capability), patch("server.modules.tts_catalog.sys.platform", "win32"), patch(
                "server.modules.tts_windows_quantized_variants.cuda_compute_capability", return_value=capability
            ):
                model = next(item for item in tts_catalog()["models"] if item["repo"] == "Aratako/Irodori-TTS-v4.1-Small")
                available = [item for item in model["variants"] if item["visible"] and item["available"]]
                self.assertEqual(min(available, key=lambda item: item["recommendedOrder"])["precision"], expected)

    def test_unknown_cuda_disables_every_quantized_variant_with_reason(self) -> None:
        variants = windows_quantized_variants("Aratako/Irodori-TTS-v4.1-Small", None)
        self.assertTrue(all(not item["available"] and item["unavailableReason"] for item in variants))

    def test_reviewed_v4_small_models_have_windows_variants(self) -> None:
        with patch("server.modules.tts_catalog.sys.platform", "win32"), patch(
            "server.modules.tts_windows_quantized_variants.cuda_compute_capability", return_value=(8, 9)
        ):
            models = {item["repo"]: item for item in tts_catalog()["models"]}
        for repo in ("Aratako/Irodori-TTS-v4.1-Small", "Aratako/Irodori-TTS-v4-Small", "phasefield-audio/Irodori-TTS-v4.1-Anime", "Aratako/Irodori-TTS-v4-Large"):
            visible = [item for item in models[repo]["variants"] if item["visible"]]
            self.assertEqual([item["precision"] for item in visible], ["W8A16", "FP32", "W8A8", "W4A16", "FP8/BF16", "FP8 Dynamic"])
            self.assertEqual(min(visible, key=lambda item: item["recommendedOrder"])["precision"], "W8A16")
            self.assertTrue(all(item.get("checkpointFile") for item in visible))
        for repo in ("Aratako/Irodori-TTS-v4.1-Small-MF", "Aratako/Irodori-TTS-600M-v3-VoiceDesign", "Aratako/Irodori-TTS-500M-v3"):
            visible = [item for item in models[repo]["variants"] if item["visible"]]
            self.assertEqual([item["precision"] for item in visible], ["FP32"])

    def test_quantized_download_is_checkpoint_plus_shared_tokenizer_only(self) -> None:
        variant = windows_quantized_variants("Aratako/Irodori-TTS-v4.1-Small", (8, 9))[0]
        self.assertEqual(set(variant["downloadFiles"]), {
            "int8-weight-only/model.safetensors", "README.md",
            "tokenizer/tokenizer.json", "tokenizer/tokenizer_config.json",
        })
        self.assertEqual({entry["path"] for entry in variant["artifactFiles"]}, set(variant["downloadFiles"]))
        self.assertEqual(variant["computePrecision"], "bf16")

    def test_anime_quantized_files_are_pinned_to_its_existing_revision(self) -> None:
        variants = windows_quantized_variants("phasefield-audio/Irodori-TTS-v4.1-Anime", (8, 9))
        self.assertEqual({item["revision"] for item in variants}, {"6b259f5baa5e236b3d14cbd1f8555ca87d92b530"})
        self.assertEqual(variants[0]["repo"], "phasefield-audio/Irodori-TTS-v4.1-Anime")
        self.assertEqual(variants[0]["modelSha256"], "8933f931ef2479364748a048c6613e690215afca175b06e4adfb5345eece9b0c")


    def test_large_macos_preserves_fp32_and_compatible_pinned_engine(self) -> None:
        with patch("server.modules.tts_catalog.sys.platform", "darwin"):
            catalog = tts_catalog()
        large = next(item for item in catalog["models"] if item["repo"] == "Aratako/Irodori-TTS-v4-Large")
        self.assertEqual([v["precision"] for v in large["variants"] if v["visible"]], ["FP32", "BF16", "8bit"])
        self.assertEqual(large["revision"], "2e0c55428ce97268a507f1feeb2478f8d9148e8b")
        self.assertEqual(large["modelSha256"], "0f3de3cdcb8cb82ac2d0089f2c051ab99e12eb7270625d06e3d1d303bad9e63c")
        engine = next(item for item in catalog["engines"] if item["id"] in large["supportedEngineIds"])
        self.assertEqual(engine["commit"], "89f9d8fbd4d51ea019867ee1197725ede1df13c5")
        self.assertIn(large["id"], engine["supportedModelIds"])
        self.assertTrue(large["supportsRuntimeCfg"] and large["supportsQualityPresets"])
        self.assertIsNone(large["fixedSteps"])
        self.assertEqual(large["license"], "Gemma")
        self.assertIn("Gemma", large["notice"])
        self.assertFalse(large["legacy"])
        self.assertEqual(min(catalog["models"], key=lambda item: item["recommendedOrder"])["repo"], "Aratako/Irodori-TTS-v4.1-Small")
        fp32 = next(v for v in large["variants"] if v["precision"] == "FP32")
        self.assertEqual(large["downloadFiles"], fp32["downloadFiles"])
        self.assertEqual(large["artifactFiles"], fp32["artifactFiles"])
        self.assertEqual({a["path"] for a in fp32["artifactFiles"]}, set(fp32["downloadFiles"]))

    def test_large_quantization_pins_its_tokenizer_not_small_and_preserves_terms(self) -> None:
        variants = windows_quantized_variants("Aratako/Irodori-TTS-v4-Large", (8, 9))
        self.assertEqual(len(variants), 5)
        for variant in variants:
            self.assertEqual(variant["revision"], "bdef9592db4426bd1c99ccdf0cfc3a213223fb61")
            self.assertEqual(variant["computePrecision"], "bf16")
            artifacts = {a["path"]: a["sha256"] for a in variant["artifactFiles"]}
            self.assertEqual(set(artifacts), set(variant["downloadFiles"]))
            self.assertEqual(artifacts["tokenizer/tokenizer.json"], "f5b325224482ec441ec5fbe2a5ac08c3758e0f9605f6e54368e31f736fcfb01d")
            self.assertTrue({"NOTICE", "GEMMA_TERMS_OF_USE.md", "GEMMA_PROHIBITED_USE_POLICY.md"}.issubset(artifacts))
        self.assertEqual(variants[0]["sizeBytes"], 3839580074 + 33384387 + 802 + 96 + 10542 + 3852 + 4628 )

if __name__ == "__main__":
    unittest.main()
