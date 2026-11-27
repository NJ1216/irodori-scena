from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import HTTPException
from server.app import AcceptCandidateRequest, CandidateRequest
from server.modules import character_routes
from server.modules.character_routes import (
    VOICE_DESIGN_AUDIO_QUALITY_SUFFIX,
    _voice_design_inference_caption,
    accept_candidate,
    clear_candidates,
    create_candidates,
)
from server.modules.common import audio_digest
from server.modules.inference import INFERENCE_SYNTHESIS_LOCK, run_irodori


class CharacterCandidateAcceptanceTests(unittest.TestCase):
    @staticmethod
    def _voice_design_deps(voice_design: bool):
        original_deps = character_routes.deps

        class DependencyProxy:
            def selected_model_capabilities(self):
                return {"voiceDesign": voice_design, "combinedReferenceCaption": voice_design}

            def __getattr__(self, name):
                return getattr(original_deps, name)

        return DependencyProxy()

    def test_irodori_synthesis_rejects_a_second_concurrent_request(self) -> None:
        self.assertTrue(INFERENCE_SYNTHESIS_LOCK.acquire(blocking=False))
        try:
            with self.assertRaises(HTTPException) as error:
                run_irodori(
                    text="こんにちは。",
                    caption="穏やかに話す",
                    output=Path("/tmp/candidate.wav"),
                    seed=1,
                    ref_wav=None,
                    quality="fast",
                )
        finally:
            INFERENCE_SYNTHESIS_LOCK.release()

        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail["code"], "operation_conflict")

    def test_voice_design_quality_suffix_is_not_duplicated(self) -> None:
        caption = f"男。{VOICE_DESIGN_AUDIO_QUALITY_SUFFIX}"

        self.assertEqual(_voice_design_inference_caption(caption), caption)

    def test_voice_design_rejects_an_unsupported_model_with_a_capability_code(self) -> None:
        proxy = self._voice_design_deps(False)
        proxy.require_tts_available = lambda: None
        with patch.object(character_routes, "deps", proxy):
            with self.assertRaises(HTTPException) as error:
                create_candidates(
                    CandidateRequest(
                        keywords="落ち着いた声",
                        sample_text="こんにちは。",
                    )
                )

        self.assertEqual(error.exception.status_code, 422)
        self.assertEqual(error.exception.detail["code"], "tts_model_unsupported_voice_design")

    def test_clearing_candidates_discards_an_in_flight_generation(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            media_root = root / "media"
            project: dict[str, object] = {
                "settings": {},
                "candidates": [{"id": "old-candidate", "file": str(media_root / "candidates" / "old.wav")}],
            }
            generated = media_root / "candidates" / "new.wav"
            generated.parent.mkdir(parents=True)
            generated.write_bytes(b"RIFF new candidate")

            def generate_then_clear(**_kwargs):
                clear_candidates()
                return [generated]

            with (
                patch.object(character_routes, "deps", self._voice_design_deps(True)),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.inference.run_irodori", side_effect=generate_then_clear),
                patch(
                    "server.modules.pronunciation_dictionary.apply_pronunciation_dictionary",
                    side_effect=lambda text, _caption: text,
                ),
                patch("server.modules.export_service.require_tts_available"),
                patch("server.modules.constants.MEDIA_ROOT", media_root),
                patch("server.modules.common.new_id", side_effect=["candidate-batch", "candidate-new"]),
                patch("server.modules.character_profiles.media_url", return_value="/api/media/candidates/new.wav"),
                patch("server.modules.runtime_state.VOICE_CANDIDATE_GENERATION_EPOCH", 0),
                patch("server.modules.voice_reference.validate_voice_design_clip", return_value=4.2),
            ):
                result = create_candidates(
                    CandidateRequest(keywords="落ち着いた声", sample_text="こんにちは。よろしくお願いします。", count=1),
                )

            self.assertEqual(result, {"candidates": []})
            self.assertEqual(project["candidates"], [])
            self.assertFalse(generated.exists())

    def test_audio_digest_is_stable_for_reference_audio(self) -> None:
        with TemporaryDirectory() as directory:
            audio = Path(directory) / "reference.wav"
            audio.write_bytes(b"RIFF test audio")

            self.assertEqual(audio_digest(audio), audio_digest(audio))

    def test_baseline_candidate_uses_its_own_speech_rate_not_project_setting(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "candidate.wav"
            output.write_bytes(b"RIFF candidate")
            project: dict[str, object] = {"settings": {"speechRate": 1.8}, "candidates": []}
            captured: dict[str, object] = {}

            def generate(**kwargs):
                captured.update(kwargs)
                return [output]

            with (
                patch.object(character_routes, "deps", self._voice_design_deps(True)),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project"),
                patch("server.modules.inference.run_irodori", side_effect=generate),
                patch(
                    "server.modules.pronunciation_dictionary.apply_pronunciation_dictionary",
                    side_effect=lambda text, _caption: text,
                ),
                patch("server.modules.export_service.require_tts_available"),
                patch("server.modules.voice_reference.validate_voice_design_clip", return_value=4.2),
                patch("server.modules.constants.MEDIA_ROOT", Path(directory)),
                patch("server.modules.common.new_id", side_effect=["candidate-batch", "candidate-1"]),
                patch("server.modules.character_profiles.media_url", return_value="/api/media/candidate.wav"),
            ):
                result = create_candidates(
                    CandidateRequest(
                        keywords="互換用",
                        voice_design={
                            "age": "小学校低学年",
                            "gender": "男性",
                            "pitch": "やや高い",
                            "qualities": ["ハスキー", "太い"],
                            "style": "威厳のある",
                            "notes": "語尾は短く",
                        },
                        sample_text="こんにちは。よろしくお願いします。",
                        count=1,
                        speech_rate=1.0,
                        text_cfg=4.2,
                        voice_cfg=6.3,
                        caption_cfg=7.4,
                    )
                )

            self.assertEqual(
                captured["caption"],
                "小学校低学年の声。男性の声。やや高い声。ハスキーな声質。太い声質。威厳のある話し方。語尾は短く。コンデンサーマイクで近接収録したような、クリアで明瞭な音質。",
            )
            self.assertEqual(
                result["candidates"][0]["keywords"],
                "小学校低学年の声。男性の声。やや高い声。ハスキーな声質。太い声質。威厳のある話し方。語尾は短く。",
            )
            self.assertEqual(result["candidates"][0]["voiceDesign"]["qualities"], ["ハスキー", "太い"])
            self.assertEqual(captured["generation_settings"]["speechRate"], 1.0)
            self.assertEqual(captured["generation_settings"]["steps"], 40)
            self.assertEqual(captured["generation_settings"]["textCfg"], 4.2)
            self.assertEqual(captured["generation_settings"]["voiceCfg"], 6.3)
            self.assertEqual(captured["generation_settings"]["captionCfg"], 7.4)
            self.assertEqual(captured["quality"], "quality")

    def _request(self) -> AcceptCandidateRequest:
        return AcceptCandidateRequest(candidate_id="candidate-1", name="彩", profile="穏やか")

    def _project(self, source: Path) -> dict[str, object]:
        return {
            "characters": [],
            "candidates": [{"id": "candidate-1", "file": str(source), "keywords": "落ち着いた声"}],
        }

    def test_accept_candidate_keeps_source_until_metadata_is_saved(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidates" / "candidate.wav"
            source.parent.mkdir()
            source.write_bytes(b"RIFF candidate")
            project = self._project(source)
            global_root = root / "global-media"
            saved_projects: list[dict[str, object]] = []
            saved_characters: list[list[dict[str, object]]] = []

            with (
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.read_global_characters", return_value=[]),
                patch("server.modules.project_repository.write_project", side_effect=saved_projects.append),
                patch("server.modules.project_repository.write_global_characters", side_effect=saved_characters.append),
                patch("server.modules.constants.GLOBAL_MEDIA_ROOT", global_root),
                patch("server.modules.common.new_id", return_value="character-new"),
            ):
                character = accept_candidate(self._request())

            target = global_root / "characters" / "character-new" / "reference.wav"
            self.assertEqual(character["id"], "character-new")
            self.assertTrue(target.is_file())
            self.assertFalse(source.exists())
            self.assertEqual(saved_characters, [[character]])
            self.assertEqual(saved_projects[0]["candidates"], [])

    def test_accept_candidate_keeps_source_when_character_metadata_fails(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "candidates" / "candidate.wav"
            source.parent.mkdir()
            source.write_bytes(b"RIFF candidate")
            global_root = root / "global-media"

            with (
                patch("server.modules.project_repository.read_project", return_value=self._project(source)),
                patch("server.modules.project_repository.read_global_characters", return_value=[]),
                patch("server.modules.project_repository.write_global_characters", side_effect=OSError("disk full")),
                patch("server.modules.constants.GLOBAL_MEDIA_ROOT", global_root),
                patch("server.modules.common.new_id", return_value="character-new"),
                patch("server.modules.character_profiles.character_record", return_value={"id": "character-new"}),
                self.assertRaisesRegex(OSError, "disk full"),
            ):
                accept_candidate(self._request())

            self.assertTrue(source.is_file())
            self.assertFalse((global_root / "characters" / "character-new" / "reference.wav").exists())
