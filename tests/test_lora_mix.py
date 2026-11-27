"""Exact persistence and all-or-nothing runtime composition without real inference."""
import scena_test_isolation  # noqa: F401
import io
import json
import zipfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from pydantic import ValidationError

from server import app as _app  # noqa: F401
from server.modules import cast_exchange, character_routes, constants, project_repository
from server.modules.cast_identity import character_content_fingerprint
from server.modules.cast_sync import project_snapshot_from_global
from server.modules.export_service import line_render_signature
from server.modules.lora_mix import LoraMix, apply_mix_patch, effective_mix, generation_mix, resolve_mix
from server.modules.lora_asset_lifecycle import _references
from server.modules.models import UpdateCharacterRequest
from server.modules.project_models import PersistedCharacter, PersistedTake
from server.scena_mlx_lora import AdapterSession, adapter_digest, blend_updates, build_updates
from test_lora_persistence import wav
from test_lora_mlx import Arrays, CONFIG, DURATION, Model, TARGET, adapter_weights

IDENTITY = {"assetId": "first", "adapterHash": "a" * 64, "baseModelRepo": "Aratako/Irodori-TTS-v4.1-Small", "baseModelRevision": "2b28324dc263ed5e6638b3cf3dd94c82ead07b4b"}
MIX = {"version": 1, "baseWeight": 2500, "entries": [{**IDENTITY, "weight": 7500}]}


class MixPersistenceTests(unittest.TestCase):
    def test_legacy_conversion_is_read_only_and_take_never_borrows_cast(self):
        for enabled, weight in ((True, 10000), (False, 0)):
            source = {"lora": {**IDENTITY, "enabled": enabled}}
            self.assertEqual(effective_mix(source)["entries"][0]["weight"], weight)
            self.assertNotIn("loraMix", source)
        mix, descriptor = generation_mix({"loraMix": MIX}, {})
        self.assertEqual(mix["baseWeight"], 10000)
        self.assertIsNone(descriptor)

    def test_exact_integer_total_limit_duplicate_and_path_rejection(self):
        for changed in ({**MIX, "baseWeight": 2499}, {**MIX, "baseWeight": 2500.0},
                        {**MIX, "entries": [{**MIX["entries"][0], "path": "/private/path"}]},
                        {"baseWeight": 0, "entries": [{**IDENTITY, "weight": 5000}] * 2},
                        {"baseWeight": 0, "entries": [{**IDENTITY, "assetId": str(i), "weight": 2000} for i in range(5)]}):
            with self.subTest(changed=changed), self.assertRaises(ValidationError):
                LoraMix.model_validate(changed)

    def test_patch_omission_roundtrip_and_usage_includes_zero_members(self):
        cast = {"loraMix": MIX}
        apply_mix_patch(cast, UpdateCharacterRequest(name="name"))
        self.assertEqual(cast["loraMix"], MIX)
        apply_mix_patch(cast, UpdateCharacterRequest(name="name", loraMix=None))
        self.assertIsNone(cast["loraMix"])
        character = PersistedCharacter(id="cast", name="name", referenceAudioUrl="ref", referenceFile="ref", createdAt=1, loraMix=MIX)
        self.assertEqual(PersistedCharacter.model_validate_json(character.model_dump_json()).loraMix.model_dump(), MIX)
        take = PersistedTake(id="take", audioUrl="audio", seed=0, quality="fast", createdAt=1, loraMix=MIX)
        self.assertEqual(PersistedTake.model_validate_json(take.model_dump_json()).loraMix.model_dump(), MIX)
        self.assertTrue(_references({"loraMix": {"entries": [{**IDENTITY, "weight": 0}]}}, "first"))

    def test_zero_members_are_not_resolved_and_bad_sibling_fails_whole_mix(self):
        mix = {"baseWeight": 5000, "entries": [{**IDENTITY, "weight": 5000}, {**IDENTITY, "assetId": "zero", "weight": 0}]}
        with patch("server.modules.lora_assets.resolve_lora_asset", return_value={"path": "managed"}) as resolve:
            descriptor = resolve_mix(mix)
            self.assertEqual(len(descriptor["adapters"]), 1)
            resolve.assert_called_once()
        mix["baseWeight"] = 0
        mix["entries"][1]["weight"] = 5000
        with patch("server.modules.lora_assets.resolve_lora_asset", side_effect=[{"path": "managed"}, ValueError("bad sibling")]), self.assertRaises(ValueError):
            resolve_mix(mix)

    def test_mix_changes_cast_and_render_identity_and_global_patch(self):
        character = {"id": "cast", "name": "name", "loraMix": MIX, "scope": "global"}
        changed = {**character, "loraMix": {**MIX, "baseWeight": 5000, "entries": [{**MIX["entries"][0], "weight": 5000}]}}
        self.assertNotEqual(character_content_fingerprint(character), character_content_fingerprint(changed))
        project = {"characters": [character], "settings": {}}
        line = {"id": "line", "text": "台詞", "characterId": "cast"}
        self.assertNotEqual(line_render_signature(project, line), line_render_signature({**project, "characters": [changed]}, line))
        with (patch.object(project_repository, "read_project", return_value=project),
              patch.object(project_repository, "read_global_characters", return_value=[dict(character)]),
              patch.object(project_repository, "write_global_characters") as write,
              patch.object(project_repository, "write_project"),
              patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]),
              patch("server.modules.pronunciation_dictionary.sync_character_pronunciations"),
              patch("server.modules.cast_context_cache.invalidate_cast_context")):
            character_routes.update_character("cast", UpdateCharacterRequest(name="name", loraMix=changed["loraMix"]))
            self.assertEqual(write.call_args.args[0][0]["loraMix"], changed["loraMix"])
            character_routes.update_character("cast", UpdateCharacterRequest(name="name"))
            self.assertEqual(character["loraMix"], changed["loraMix"])

    def test_global_snapshot_and_exchange_preserve_mix_without_adapter_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference.wav"
            wav(reference)
            character = {"id": "cast", "name": "name", "referenceFile": str(reference), "loraMix": MIX, "sampleText": "独自台詞"}
            with patch.object(constants, "MEDIA_ROOT", root / "project"):
                snapshot = project_snapshot_from_global(character)
                self.assertEqual(snapshot["loraMix"], MIX)
                self.assertEqual(snapshot["sampleText"], "独自台詞")
            payload = cast_exchange._archive_bytes(character)
            archive_path = root / "test.scenacast"
            archive_path.write_bytes(payload)
            with zipfile.ZipFile(io.BytesIO(payload)) as archive:
                self.assertEqual(set(archive.namelist()), {"manifest.json", "reference.wav"})
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["loraMix"], MIX)
            with patch.object(project_repository, "read_global_characters", return_value=[]):
                prepared = cast_exchange.prepare_cast_import(cast_exchange.CastImportPrepareRequest(paths=[str(archive_path)]))
            try:
                self.assertEqual(prepared["items"][0]["incoming"]["loraMix"], MIX)
                self.assertEqual(prepared["items"][0]["incoming"]["sampleText"], "独自台詞")
            finally:
                cast_exchange.cancel_cast_import(cast_exchange.CastImportCancelRequest(session_id=prepared["sessionId"]))


class MixWorkerTests(unittest.TestCase):
    def test_mixing_does_not_disguise_a_quantized_original_as_fp32(self):
        model = Model()
        model.weights[TARGET] = model.weights[TARGET].astype(np.int16)
        session = AdapterSession(model, arrays=Arrays, flatten=lambda values: values.items())
        with self.assertRaisesRegex(ValueError, "unquantized"):
            session.prepare({"baseWeight": 5000, "adapters": [{"weight": 5000}]})


    def test_weighted_attention_leaves_duration_at_base(self):
        model = Model()
        first = build_updates(model.weights, adapter_weights(), CONFIG, Arrays)
        second = {TARGET: np.full((2, 2), 5, dtype=np.float32), DURATION: np.full((1, 2), 3, dtype=np.float32)}
        result = blend_updates(model.weights, [(0.25, first), (0.5, second)], Arrays)
        np.testing.assert_array_equal(result[TARGET], np.full((2, 2), 3.5))
        self.assertNotIn(DURATION, result)
        np.testing.assert_array_equal(model.weights[DURATION], np.ones((1, 2)))
        np.testing.assert_array_equal(model.weights[TARGET], np.ones((2, 2)))

    def test_endpoints_all_or_nothing_restore_failure_and_next_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            descriptors = []
            for name in ("first", "second"):
                directory = root / name
                directory.mkdir()
                (directory / "adapter_config.json").write_text(json.dumps(CONFIG))
                (directory / "adapter_model.safetensors").write_bytes(b"fixture")
                descriptors.append({**IDENTITY, "assetId": name, "path": str(directory), "adapterHash": adapter_digest(directory), "weight": 5000})
            model = Model()
            original = dict(model.weights)
            session = AdapterSession(model, arrays=Arrays, flatten=lambda values: values.items())
            with patch.object(Arrays, "load", return_value=adapter_weights()):
                with session.scoped({"baseWeight": 10000, "adapters": []}):
                    self.assertIs(model.weights[TARGET], original[TARGET])
                endpoint = {"baseWeight": 0, "adapters": [{**descriptors[0], "weight": 10000}]}
                np.testing.assert_array_equal(session.prepare(endpoint)[TARGET], session.prepare(descriptors[0])[TARGET])
                for dtype in (np.float16, np.float32):
                    voice_model = Model()
                    voice_model.weights = {key: value.astype(dtype) for key, value in voice_model.weights.items()}
                    duration_original = voice_model.weights[DURATION]
                    voice_session = AdapterSession(voice_model, arrays=Arrays, flatten=lambda values: values.items())
                    for descriptor in (descriptors[0], endpoint, {"baseWeight": 5000, "adapters": [{**descriptors[0], "weight": 5000}]}, {"baseWeight": 0, "adapters": descriptors}):
                        with self.subTest(dtype=dtype, descriptor=descriptor), voice_session.scoped(descriptor):
                            self.assertIs(voice_model.weights[DURATION], duration_original)
                            self.assertNotIn(DURATION, voice_session.changed)
                            self.assertFalse(np.array_equal(voice_model.weights[TARGET], np.ones((2, 2))))
                        self.assertIs(voice_model.weights[DURATION], duration_original)

                with self.assertRaises(RuntimeError), session.scoped(endpoint):
                    raise RuntimeError("synthesis failed")
                self.assertIs(model.weights[TARGET], original[TARGET])
                with session.scoped(None):
                    self.assertIs(model.weights[TARGET], original[TARGET])
                bad = {"baseWeight": 0, "adapters": [descriptors[0], {**descriptors[1], "adapterHash": "0" * 64}]}
                with self.assertRaises(ValueError), session.scoped(bad):
                    self.fail("must not enter synthesis")
                self.assertIs(model.weights[TARGET], original[TARGET])
                model.fail_once = True
                with self.assertRaises(RuntimeError), session.scoped({"baseWeight": 0, "adapters": descriptors}):
                    self.fail("partial mutation must fail")
                for key in original:
                    self.assertIs(model.weights[key], original[key])
