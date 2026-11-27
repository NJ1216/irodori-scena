import scena_test_isolation  # noqa: F401
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server.app import CharacterProfileSuggestionRequest, suggest_character_profile_completion
from server.modules.profile_suggestions import PROFILE_FIELDS, PROFILE_SYSTEM
from server.modules.profile_relation_resolver import build_address_registries, parse_relation_response


def request_with_casts(count: int) -> CharacterProfileSuggestionRequest:
    details = {key: (["既存"] if key in {"aliases", "firstPerson", "secondPerson"} else "既存")
               for key in PROFILE_FIELDS if key != "gender"}
    return CharacterProfileSuggestionRequest(
        model="test-model", name="主人公", idea="雨の日だけ開く古書店の店主",
        profile_details=details,
        other_casts=[{"id": f"cast-{index}", "name": f"相手{index}",
                      "profile_details": {"role": f"役割{index}"}} for index in range(count)],
    )


class ProfileSuggestionChunkTests(unittest.TestCase):
    def test_fill_missing_without_blank_targets_reports_actionable_input_error(self) -> None:
        details = {
            key: (["既存"] if key in {"aliases", "firstPerson", "secondPerson"} else "既存")
            for key in PROFILE_FIELDS
        }
        request = CharacterProfileSuggestionRequest(
            model="test-model", name="設定済み", profile_details=details, scope="all",
        )
        with patch("server.modules.llm_completion_service.complete_records") as completion:
            with self.assertRaisesRegex(Exception, "選択した範囲に空欄の項目がありません") as raised:
                suggest_character_profile_completion(request)
        self.assertEqual(raised.exception.status_code, 422)
        completion.assert_not_called()

    def test_allows_every_text_field_to_be_blank_and_generates_partial_profile(self) -> None:
        request = CharacterProfileSuggestionRequest(
            model="test-model", name="", profile="", idea="", profile_details={}, scope="profile",
        )
        captured = {}

        def completion(*_args, **kwargs):
            captured.update(kwargs["user"])
            return "FIELD|aliases|リリ／りっちゃん\nFIELD|personality|穏やかで好奇心旺盛"

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/blank-profile")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
        ):
            result = suggest_character_profile_completion(request)
        self.assertEqual(result["profileDetails"]["aliases"], ["リリ", "りっちゃん"])
        self.assertEqual(result["profileDetails"]["personality"], "穏やかで好奇心旺盛")
        self.assertEqual(captured["character_name"], "名称未設定のキャスト")
        self.assertEqual(captured["existing_settings"], {})
        self.assertEqual(captured["existing_free_memo"], "（未設定）")

    def test_schema_profile_values_keep_newlines_and_pipes(self) -> None:
        request = CharacterProfileSuggestionRequest(
            model="test-model", name="", idea="", profile_details={}, scope="profile",
        )
        records = [{"field": "background", "value": "line1\nline2 | x"}, {"field": "age", "value": "19歳"}]
        result = SimpleNamespace(records=records, mode="schema", manifest=[])
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/profile-pipes")),
            patch("server.modules.llm_completion_service.complete_records", return_value=result),
        ):
            details = suggest_character_profile_completion(request)["profileDetails"]
        self.assertEqual(details["background"], "line1\nline2 | x")
        self.assertEqual(details["age"], "19歳")

    def test_gemma_nine_legacy_relation_variants_recover_both_fields(self) -> None:
        target = {"id": "cast-0", "name": "相手0", "source_cast": {
            "id": "cast-0", "name": "相手0", "profile_details": {},
        }, "missing_relation_fields": {"address", "relationship"}}
        registries = build_address_registries([target], {"secondPerson": []})
        fixture = Path(__file__).parent / "fixtures" / "gemma_relation_legacy_variants.json"
        for content in json.loads(fixture.read_text(encoding="utf-8")):
            with self.subTest(content=content):
                parsed, _ = parse_relation_response(content, [target], registries)
                self.assertEqual(parsed, {"cast-0": {
                    "address": "相手0さん", "relationship": "雨の日に本音を話せる友人。",
                }})

    def test_profile_prompt_considers_ensemble_and_rejects_duplicate_identity_fields(self) -> None:
        request = CharacterProfileSuggestionRequest(
            model="test-model", name="新規キャスト", scope="profile",
            profile_details={"personality": "荒っぽいが義理堅い"},
            other_casts=[{
                "id": "existing", "name": "剛田 武",
                "profile_details": {"familyName": "剛田", "givenName": "武", "aliases": ["タケ"]},
            }],
        )
        captured = {}

        def completion(*_args, **kwargs):
            captured.update(kwargs["user"])
            return ("FIELD|familyName|剛田\nFIELD|familyNameKana|ごうだ\n"
                    "FIELD|givenName|新\nFIELD|aliases|タケ／アラタ\nFIELD|age|21歳")

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/name-diversity")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
        ):
            result = suggest_character_profile_completion(request)
        self.assertNotIn("familyName", result["profileDetails"])
        self.assertNotIn("familyNameKana", result["profileDetails"])
        self.assertEqual(result["profileDetails"]["givenName"], "新")
        self.assertEqual(result["profileDetails"]["aliases"], ["アラタ"])
        self.assertEqual(result["profileDetails"]["age"], "21歳")
        self.assertEqual(captured["used_identity_values"]["familyNames"], ["剛田"])
        self.assertEqual(captured["ensemble_context"][0]["display_name"], "剛田 武")
        self.assertIn("荒っぽい人物だから「剛田」", PROFILE_SYSTEM)

    def test_profile_scope_skips_relationship_generation(self) -> None:
        request = request_with_casts(7)
        request.scope = "profile"
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/profile-only")),
            patch("server.modules.llm_client.openai_text_completion", return_value="FIELD|性別|女性") as completion,
        ):
            result = suggest_character_profile_completion(request)
        self.assertEqual(completion.call_count, 1)
        self.assertEqual(result["profileDetails"], {"gender": "女性"})
        self.assertEqual(result["requestedRelationFields"], 0)

    def test_relations_scope_skips_profile_generation(self) -> None:
        request = request_with_casts(7)
        request.scope = "relations"

        def completion(*_args, **kwargs):
            return "\n".join(
                f"RELATION|{item['id']}|呼び方|{item['name']}さん\n"
                f"RELATION|{item['id']}|関係性|信頼できる友人"
                for item in kwargs["user"]["relation_targets"]
            )

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/relations-only")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion) as llm,
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request)
        self.assertEqual(llm.call_count, 2)
        self.assertEqual(result["requestedProfileFields"], 0)
        self.assertEqual(result["acceptedRelationFields"], 14)
        self.assertNotIn("gender", result["profileDetails"])

    def test_seven_targets_use_profile_then_six_and_one_relation_calls(self) -> None:
        calls = []

        def completion(*_args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return "FIELD|性別|女性"
            targets = kwargs["user"]["relation_targets"]
            return "\n".join(f"RELATION|{item['id']}|呼び方|{item['name']}さん" for item in targets)

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/profile-chunks")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request_with_casts(7))

        self.assertEqual([len(call["user"].get("relation_targets", [])) for call in calls], [0, 6, 1])
        self.assertEqual(result["acceptedRelationFields"], 7)
        self.assertEqual(result["incompleteTargetIds"], [f"cast-{index}" for index in range(7)])
        self.assertEqual(result["incompleteFields"], [f"cast-{index}:relationship" for index in range(7)])
        cores = [call["user"]["immutable_character_core"] for call in calls[1:]]
        self.assertEqual(cores[0], cores[1])
        self.assertEqual(cores[0]["gender"], "女性")
        self.assertTrue(all(call["user"]["author_idea"] == "雨の日だけ開く古書店の店主" for call in calls[1:]))
        self.assertNotIn("相手6", str(calls[1]["user"]))
        self.assertTrue(all("castRelations" not in call["user"]["immutable_character_core"] for call in calls[1:]))

    def test_replace_does_not_send_old_relation_values(self) -> None:
        request = request_with_casts(7)
        request.mode = "replace_details"
        request.profile_details["castRelations"] = {
            "cast-0": {"address": "旧呼称", "relationship": "旧関係"},
        }
        calls = []

        def completion(*_args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return "\n".join(f"FIELD|{key}|新しい値" for key in PROFILE_FIELDS)
            return "\n".join(
                f"RELATION|{item['id']}|呼び方|新呼称\nRELATION|{item['id']}|関係性|新関係"
                for item in kwargs["user"]["relation_targets"]
            )

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/profile-replace")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request)
        self.assertNotIn("旧呼称", str(calls))
        self.assertNotIn("旧関係", str(calls))
        self.assertEqual(result["profileDetails"]["castRelations"]["cast-0"],
                         {"relationship": "新関係"})
        self.assertIn("cast-0:address", result["incompleteFields"])

    def test_candidate_protocol_resolves_names_aliases_titles_and_pronouns(self) -> None:
        request = request_with_casts(1)
        request.scope = "relations"
        request.profile_details["secondPerson"] = ["あなた"]
        request.other_casts[0]["profile_details"].update({
            "familyName": "如月", "givenName": "紗良", "aliases": ["さーちゃん"],
        })
        response = "RELATION|cast-0|呼び方候補|c2|h2|name\nRELATION|cast-0|関係性|幼なじみ"
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/candidates")),
            patch("server.modules.llm_client.openai_text_completion", return_value=response),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request)
        self.assertEqual(result["profileDetails"]["castRelations"]["cast-0"], {
            "address": "紗良ちゃん", "relationship": "幼なじみ",
        })

    def test_setting_address_requires_basis_but_keeps_relationship(self) -> None:
        request = request_with_casts(1)
        request.scope = "relations"
        response = ("RELATION|cast-0|設定呼称|文学少女|h2|name\n"
                    "RELATION|cast-0|関係性|読書仲間")
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/custom")),
            patch("server.modules.llm_client.openai_text_completion", return_value=response),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request)
        self.assertEqual(result["profileDetails"]["castRelations"], {
            "cast-0": {"relationship": "読書仲間"},
        })

    def test_replace_normalizes_existing_unnatural_address_without_ai_replacement(self) -> None:
        request = request_with_casts(1)
        request.scope = "relations"
        request.mode = "replace_details"
        request.profile_details["castRelations"] = {"cast-0": {"address": "あなたさん"}}
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/normalize")),
            patch("server.modules.llm_client.openai_text_completion",
                  return_value="RELATION|cast-0|呼び方候補|unknown|h0|name\nRELATION|cast-0|関係性|友人"),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request)
        self.assertEqual(result["profileDetails"]["castRelations"]["cast-0"], {
            "address": "あなた", "relationship": "友人",
        })

    def test_invalid_middle_chunk_does_not_discard_later_valid_values(self) -> None:
        responses = ["FIELD|性別|女性", "壊れた応答", "RELATION|cast-6|関係性|長年の相談相手"]
        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/profile-chunks")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=responses),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request_with_casts(7))
        self.assertEqual(result["profileDetails"]["castRelations"],
                         {"cast-6": {"relationship": "長年の相談相手"}})
        self.assertEqual(result["incompleteTargetIds"], [f"cast-{index}" for index in range(7)])

    def test_cancellation_keeps_completed_relation_chunk(self) -> None:
        request = request_with_casts(7)
        request.scope = "relations"
        calls = []

        def completion(*_args, **kwargs):
            calls.append(kwargs)
            return "\n".join(
                f"RELATION|{item['id']}|関係性|確定済み"
                for item in kwargs["user"]["relation_targets"]
            )

        with (
            patch("server.modules.workspace.draft_debug_directory", return_value=Path("/tmp/cancel-partial")),
            patch("server.modules.llm_client.openai_text_completion", side_effect=completion),
            patch("server.modules.draft_capability.select_call_context", return_value={}),
        ):
            result = suggest_character_profile_completion(request, should_cancel=lambda: bool(calls))
        self.assertEqual(len(result["profileDetails"]["castRelations"]), 6)
        self.assertIn("cast-6", result["incompleteTargetIds"])
        self.assertEqual(result["profileDetails"]["castRelations"]["cast-0"], {"relationship": "確定済み"})


if __name__ == "__main__":
    unittest.main()
