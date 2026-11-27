from __future__ import annotations

import scena_test_isolation  # noqa: F401
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server import app as _app  # noqa: F401
from server.modules import constants, export_service, inference, project_repository, tts_registry


class TtsVariantDeletionTests(unittest.TestCase):
    def test_deleting_variants_in_sequence_removes_the_final_model_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            models_root = root / "models"
            codecs_root = root / "codecs"
            fp32_path, mlx_path = models_root / "fp32", models_root / "mlx"
            fp32_path.mkdir(parents=True)
            mlx_path.mkdir(parents=True)
            codecs_root.mkdir()
            registry = {
                "version": 3,
                "defaultEngineId": None,
                "defaultModelId": "model",
                "engines": [],
                "libraries": [],
                "models": [{
                    "id": "model", "displayName": "Irodori", "source": "managed",
                    "path": str(fp32_path), "diskBytes": 30, "activeVariantId": "mlx-fp16",
                    "installedVariants": [
                        {"id": "pytorch-fp32", "backend": "pytorch", "precision": "FP32", "path": str(fp32_path), "diskBytes": 20},
                        {"id": "mlx-fp16", "backend": "mlx", "precision": "FP16", "path": str(mlx_path), "diskBytes": 10},
                    ],
                }],
            }

            def write_registry(value):
                registry.clear()
                registry.update(copy.deepcopy(value))

            with (
                patch.object(tts_registry, "read_tts_registry", side_effect=lambda: copy.deepcopy(registry)),
                patch.object(tts_registry, "write_tts_registry", side_effect=write_registry),
                patch.object(tts_registry, "tts_registry_view", side_effect=lambda: copy.deepcopy(registry)),
                patch.object(constants, "TTS_MODELS_ROOT", models_root),
                patch.object(constants, "TTS_CODECS_ROOT", codecs_root),
                patch.object(export_service, "active_export_job", return_value=None),
                patch.object(export_service, "active_draft_job", return_value=None),
                patch.object(project_repository, "read_project", return_value={}),
                patch.object(project_repository, "write_project"),
                patch.object(inference, "shutdown_inference_worker"),
            ):
                first = tts_registry.delete_tts_variant("model", "pytorch-fp32")
                self.assertFalse(fp32_path.exists())
                self.assertEqual((first["models"][0]["path"], first["models"][0]["diskBytes"]), (str(mlx_path), 10))

                final = tts_registry.delete_tts_variant("model", "mlx-fp16")
                self.assertFalse(mlx_path.exists())
                self.assertFalse(codecs_root.exists())
                self.assertEqual(final["models"], [])
                self.assertIsNone(final["defaultModelId"])
