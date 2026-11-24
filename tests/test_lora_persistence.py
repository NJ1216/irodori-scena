from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
import wave
import zipfile
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from server import app as _app  # noqa: F401
from server.modules import cast_exchange, character_routes, constants, project_repository, script_routes, workspace
from server.modules.cast_identity import character_content_fingerprint
from server.modules.cast_sync import project_snapshot_from_global
from server.modules.export_service import line_render_signature
from server.modules.lora_reference import LoraReference, generation_lora
from server.modules.lora_mix import effective_mix
from server.modules.models import UpdateCharacterRequest
from server.modules.project_models import PersistedCharacter, PersistedTake
from server.modules.take_restoration import validate_take_execution, validate_take_runtime


REFERENCE = {"assetId": "lora-a", "adapterHash": "a" * 64, "baseModelRepo": "Aratako/Irodori-TTS-v4.1-Small", "baseModelRevision": "b" * 40, "enabled": True}


def wav(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(24000)
        stream.writeframes(b"\0\0" * 100)


class LoraPersistenceTests(unittest.TestCase):
    def test_legacy_missing_ref_and_disabled_missing_asset_stay_off(self):
        resolve = Mock(side_effect=AssertionError("must not resolve disabled adapters"))
        with patch.dict(sys.modules, {"server.modules.lora_assets": SimpleNamespace(resolve_lora_asset=resolve)}):
            self.assertEqual(generation_lora({}, None), (None, None))
            disabled = {**REFERENCE, "enabled": False}
            self.assertEqual(generation_lora({"lora": disabled}, None), (disabled, None))
            self.assertEqual(generation_lora({"lora": REFERENCE}, {}), (None, None))
            resolve.assert_not_called()

    def test_saved_take_adapter_has_priority_and_missing_enabled_fails(self):
        resolve = Mock(return_value={"path": "/managed/adapter"})
        with patch.dict(sys.modules, {"server.modules.lora_assets": SimpleNamespace(resolve_lora_asset=resolve)}):
            saved = {**REFERENCE, "assetId": "saved-adapter"}
            reference, descriptor = generation_lora({"lora": REFERENCE}, {"lora": saved})
            self.assertEqual(reference, saved)
            self.assertEqual(descriptor["path"], "/managed/adapter")
            resolve.assert_called_once_with(saved)
            resolve.side_effect = HTTPException(409, "missing")
            with self.assertRaises(HTTPException):
                generation_lora({"lora": REFERENCE}, None)

    def test_strict_identity_never_persists_machine_path(self):
        with self.assertRaises(ValidationError):
            LoraReference.model_validate({**REFERENCE, "path": "/unsafe/local/path"})
        with self.assertRaises(ValidationError):
            LoraReference.model_validate({**REFERENCE, "assetId": "../escape"})
        character = PersistedCharacter(id="cast", name="彩", referenceAudioUrl="/media/ref.wav", referenceFile="ref.wav", createdAt=1, lora=REFERENCE)
        self.assertEqual(PersistedCharacter.model_validate_json(character.model_dump_json()).lora.model_dump(), REFERENCE)
        take = PersistedTake(id="take", audioUrl="/media/take.wav", seed=1, quality="fast", createdAt=1, lora=REFERENCE, loraExecution={"applied": True})
        self.assertEqual(PersistedTake.model_validate_json(take.model_dump_json()).lora.model_dump(), REFERENCE)

    def test_unrelated_patch_preserves_adapter_and_null_removes_without_deleting_takes(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                character = {"id": "cast", "name": "彩", "scope": "global", "lora": {**REFERENCE, "enabled": enabled}}
                take = {"id": "take", "audioUrl": "/media/existing.wav"}
                project = {"id": "project", "characters": [character], "scenes": [{"lines": [{"takes": [take]}]}]}
                with ExitStack() as stack:
                    stack.enter_context(patch.object(project_repository, "read_project", return_value=project))
                    stack.enter_context(patch.object(project_repository, "read_global_characters", return_value=[dict(character)]))
                    write = stack.enter_context(patch.object(project_repository, "write_global_characters"))
                    stack.enter_context(patch.object(project_repository, "write_project"))
                    stack.enter_context(patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]))
                    stack.enter_context(patch("server.modules.pronunciation_dictionary.sync_character_pronunciations"))
                    stack.enter_context(patch("server.modules.cast_context_cache.invalidate_cast_context"))
                    character_routes.update_character("cast", UpdateCharacterRequest(name="新名"))
                    self.assertEqual(character["lora"], {**REFERENCE, "enabled": enabled})
                    self.assertEqual(write.call_args.args[0][0]["lora"], {**REFERENCE, "enabled": enabled})
                    character_routes.update_character("cast", UpdateCharacterRequest(name="新名", lora=None))
                    self.assertIsNone(character["lora"])
                    self.assertIsNone(write.call_args.args[0][0]["lora"])
                    self.assertEqual(project["scenes"][0]["lines"][0]["takes"], [take])

    def test_global_and_project_files_roundtrip_missing_adapter_without_embedded_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "media" / "characters" / "cast" / "reference.wav"
            wav(reference)
            character = {"id": "cast", "name": "彩", "createdAt": 1, "referenceFile": str(reference), "referenceAudioUrl": "/media/characters/cast/reference.wav", "lora": REFERENCE}
            project = workspace.default_project()
            project["characters"] = [character]
            with (
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", root / "project.json"),
                patch.object(constants, "MEDIA_ROOT", root / "media"),
                patch.object(constants, "ACTIVE_PROJECT_PATH", None),
                patch.object(constants, "GLOBAL_CHARACTERS_ROOT", root / "global"),
                patch.object(constants, "GLOBAL_CHARACTERS_FILE", root / "global" / "characters.json"),
                patch.object(project_repository, "resolved_project_characters", side_effect=lambda value: value),
                patch("server.modules.workspace.ensure_data_root"),
                patch("server.modules.project_pronunciation_snapshot.project_pronunciation_snapshot", return_value=[]),
            ):
                project_repository.write_global_characters([character])
                self.assertEqual(project_repository.read_global_characters()[0]["lora"], REFERENCE)
                project_repository.write_project(project)
                loaded = project_repository.read_project()
                self.assertEqual(loaded["characters"][0]["lora"], REFERENCE)
                self.assertEqual(set(root.iterdir()), {root / "media", root / "global", root / "project.json"})

    def test_adapter_change_is_cast_change_and_inflight_render_change(self):
        character = {"id": "cast", "name": "彩"}
        changed = {**character, "lora": REFERENCE}
        self.assertNotEqual(character_content_fingerprint(character), character_content_fingerprint(changed))
        project = {"characters": [character], "settings": {}, "scenes": []}
        line = {"id": "line", "characterId": "cast", "text": "台詞"}
        self.assertNotEqual(line_render_signature(project, line), line_render_signature({**project, "characters": [changed]}, line))

    def test_global_snapshot_and_cast_archive_preserve_external_ref_and_warn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            wav(reference)
            character = {"id": "cast", "name": "彩", "referenceFile": str(reference), "lora": REFERENCE}
            with patch.object(constants, "MEDIA_ROOT", root / "project"):
                self.assertEqual(project_snapshot_from_global(character)["lora"], REFERENCE)
            content = cast_exchange._archive_bytes(character)
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                self.assertEqual(json.loads(archive.read("manifest.json"))["lora"], REFERENCE)
                self.assertEqual(set(archive.namelist()), {"manifest.json", "reference.wav"})
            destination = root / "export"
            destination.mkdir()
            with patch.object(project_repository, "read_project", return_value={"characters": [character]}):
                result = cast_exchange.export_casts(cast_exchange.CastExportRequest(cast_ids=["cast"], destination_dir=str(destination)))
            self.assertTrue(result["warnings"])
            with patch.object(project_repository, "read_global_characters", return_value=[]):
                prepared = cast_exchange.prepare_cast_import(cast_exchange.CastImportPrepareRequest(paths=[result["results"][0]["path"]]))
            try:
                self.assertEqual(prepared["items"][0]["incoming"]["lora"], REFERENCE)
                self.assertTrue(prepared["warnings"])
            finally:
                cast_exchange.cancel_cast_import(cast_exchange.CastImportCancelRequest(session_id=prepared["sessionId"]))

    def test_fp16_restore_requires_saved_artifact_backend_and_precision(self):
        saved = {"variantId": "mlx-fp16", "backend": "mlx", "precision": "FP16", "artifactRepo": "converted-model", "artifactRevision": "converted"}
        model = {"variantId": "mlx-fp16", "backend": "mlx", "precision": "fp16", "repo": "converted-model", "revision": "converted"}
        validate_take_runtime(saved, {"model": model})
        validate_take_runtime({}, None)
        for key, replacement in (("variantId", "mlx-fp32"), ("precision", "FP32"), ("revision", "another-artifact"), ("backend", "pytorch"), ("repo", "different-repo")):
            with self.subTest(key=key), self.assertRaises(HTTPException) as error:
                validate_take_runtime(saved, {"model": {**model, key: replacement}})
            self.assertEqual(error.exception.status_code, 409)

    def test_restoration_checks_actual_decoder_and_runtime_metadata(self):
        saved = {"variantId": "mlx-fp16", "precision": "FP16", "artifactRepo": "converted-model", "codecArtifactRepo": "codec", "codecArtifactRevision": "decoder", "codecPrecision": "FP32"}
        actual = {"variantId": "mlx-fp16", "precision": "fp16", "artifactRepo": "converted-model", "codec": {"repo": "codec", "revision": "decoder", "precision": "fp32"}}
        validate_take_execution(saved, actual)
        for changed in ({**actual, "artifactRepo": "another-repo"}, {**actual, "precision": "FP32"}, {**actual, "codec": {**actual["codec"], "revision": "changed"}}, {**actual, "codec": {**actual["codec"], "precision": "FP16"}}):
            with self.assertRaises(HTTPException):
                validate_take_execution(saved, changed)

    def test_real_line_boundary_passes_adapter_and_records_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.wav"
            wav(reference)
            character = {"id": "cast", "referenceFile": str(reference), "lora": REFERENCE}
            project = {"characters": [character], "settings": {"seed": 1}, "scenes": [], "ttsSelection": {"engine": {"commit": "a"}, "model": {"repo": REFERENCE["baseModelRepo"], "revision": REFERENCE["baseModelRevision"]}}}
            line = {"id": "line", "characterId": "cast", "text": "こんにちは。"}
            captured = []
            def synthesize(**kwargs):
                captured.append(kwargs["lora_adapter"])
                wav(kwargs["output"])
            execution = {"variantId": "mlx-fp16", "backend": "mlx", "precision": "FP16", "artifactRepo": "mlx-model", "artifactRevision": "converted-revision", "lora": {"applied": True, "adapterHash": REFERENCE["adapterHash"], "artifactRepo": "mlx-model", "artifactRevision": "converted-revision", "precision": "FP16"}, "codec": {"repo": "mlx-codec", "revision": "decoder-revision", "precision": "fp16"}}
            descriptor = {"path": str(root / "adapter"), **REFERENCE}
            with patch.dict(sys.modules, {"server.modules.lora_assets": SimpleNamespace(resolve_lora_asset=lambda ref: descriptor)}), patch.object(constants, "MEDIA_ROOT", root / "media"), patch("server.modules.inference.run_irodori", side_effect=synthesize), patch("server.modules.inference.last_inference_execution", return_value=execution), patch("server.modules.tts_registry.selected_tts_runtime", return_value={"model": {"variantId": "mlx-fp16", "backend": "mlx", "precision": "FP16", "repo": "mlx-model", "revision": "converted-revision"}}):
                take = script_routes.create_line_take(project, line, "fast")
                self.assertEqual(take["loraMix"], effective_mix(character))
                self.assertEqual(take["loraExecution"], execution["lora"])
                self.assertEqual(take["ttsConfiguration"]["artifactRepo"], "mlx-model")
                self.assertEqual(take["ttsConfiguration"]["codecArtifactRepo"], "mlx-codec")
                self.assertEqual(take["ttsConfiguration"]["codecArtifactRevision"], "decoder-revision")
                self.assertEqual(take["ttsConfiguration"]["codecPrecision"], "fp16")
                self.assertEqual(captured, [{"version": 1, "baseWeight": 0, "adapters": [{**descriptor, "weight": 10000}]}])
                script_routes.create_line_take(project, line, "fast", restore_take={**{key: value for key, value in take.items() if key != "loraMix"}, "lora": None})
                self.assertIsNone(captured[-1])
                saved_wav = root / "media" / "takes" / "line" / f"{take['id']}.wav"
                before = saved_wav.read_bytes()
                execution["codec"] = {**execution["codec"], "revision": "changed-decoder"}
                with self.assertRaises(HTTPException):
                    script_routes.create_line_take(project, line, "fast", take_id=take["id"], restore_take=take)
                self.assertEqual(saved_wav.read_bytes(), before)
                self.assertFalse(list(saved_wav.parent.glob(".partial-*.wav")))
