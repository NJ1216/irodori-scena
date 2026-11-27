from __future__ import annotations

import scena_test_isolation  # noqa: F401
import unittest
from unittest.mock import patch

from server.app import (
    DraftRequest,
    LlmContractResult,
    LlmTransportResult,
    build_draft_packets,
    allocate_source_targets,
    extract_required_sources,
    generate_draft_dialogue,
    packet_chapters,
    planned_draft_beats,
    required_source_schema,
    draft_schema_batching_available,
    draft_theme_sections,
    draft_author_ending,
)
from server.modules.draft_plan_contracts import plan_from_records


class DraftDialogueBatchingTests(unittest.TestCase):
    def test_semantic_scene_states_become_independent_owned_beats(self) -> None:
        plan = plan_from_records(({
            "kind": "chapter", "index": 1, "title": "対話", "objective": "和解する",
            "scenes": [
                {"purpose": "誤解を明かす", "start": "対立している", "end": "原因を理解する"},
                {"purpose": "謝罪を受け入れる", "start": "迷っている", "end": "和解する"},
            ],
        },))
        beats = planned_draft_beats(plan["chapters"], 800, source_capacity=200)
        self.assertEqual([beat.source for beat in beats], ["D1.1", "D1.2"])
        self.assertIn("開始状態: 対立している", beats[0].text)
        self.assertIn("終了状態: 和解する", beats[1].text)

    def test_collapsed_title_record_retains_unambiguously_owned_chapter(self) -> None:
        plan = plan_from_records(({
            "kind": "title", "text": "配信", "index": 1,
            "objective": "配信を完了する",
            "scenes": [{"purpose": "挨拶する", "start": "配信開始", "end": "挨拶完了"}],
        },))
        self.assertEqual(plan["title"], "配信")
        self.assertEqual(len(plan["chapters"]), 1)
        self.assertIn("目的: 挨拶する", plan["chapters"][0]["beats"][0])

    def test_theme_sections_preserve_paragraphs_order_and_author_ending(self) -> None:
        theme = ("二人がパンケーキ店へ到着する。\n\n"
                 "注文してパンケーキを食べ、感想を話す。\n\n"
                 "店を出て解散する前に、次回も一緒に来る約束をする。")
        sections = draft_theme_sections(theme)
        self.assertEqual([section["text"] for section in sections], theme.split("\n\n"))
        self.assertEqual(draft_author_ending(theme, sections, [sections[-1]["text"]]), {
            "id": "AUTHOR_ENDING", "section_id": "S3",
            "text": "店を出て解散する前に、次回も一緒に来る約束をする。",
        })

    def test_long_theme_sections_split_without_losing_text(self) -> None:
        theme = "あ" * 230 + "。" + "い" * 230 + "。最後に帰宅する。"
        sections = draft_theme_sections(theme)
        self.assertTrue(all(len(section["text"]) <= 240 for section in sections))
        self.assertEqual("".join(section["text"] for section in sections), theme)
        self.assertEqual(draft_author_ending(theme, sections, ["最後に帰宅する。"]) ["text"], "最後に帰宅する。")

    def test_author_ending_is_last_owned_source_with_reserved_capacity(self) -> None:
        chapters = [{"beats": ["導入", "中盤", "転換"], "author_ending": {
            "id": "AUTHOR_ENDING", "section_id": "S3", "text": "二人が解散する。",
        }}]
        beats = planned_draft_beats(chapters, 500)
        self.assertEqual(beats[-1].source, "D1.3")
        self.assertEqual(chapters[-1]["author_ending"]["id"], "D1.3")
        self.assertEqual(len(beats), 3)
        self.assertGreaterEqual(beats[0].target_characters, 160)
        self.assertGreaterEqual(beats[-1].target_characters, 160)
        self.assertEqual(sum(beat.target_characters for beat in beats), 500)
        self.assertIn("予告や言及だけで完了扱いにしない", beats[-1].text)

    def test_production_batching_uses_any_confirmed_stream_schema_without_benchmark_gate(self) -> None:
        request = DraftRequest(base_url="http://127.0.0.1:9999/v1", model="schema-model",
                               character_ids=["cast-a"], target_minutes=1, theme="通常製品経路の確認です。")
        with patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value={
            "structuredOutput": {"streaming": {"state": "schema_validated"}},
        }):
            self.assertTrue(draft_schema_batching_available(request))

    def test_dynamic_schema_requires_every_source_for_one_two_and_three_sources(self) -> None:
        line = {"type": "object"}
        for sources in (["D1.1"], ["D1.1", "D1.2"], ["D1.1", "D1.2", "D2.1"]):
            schema = required_source_schema(sources, line)
            self.assertEqual(schema["required"], sources)
            self.assertEqual(list(schema["properties"]), sources)
            self.assertFalse(schema["additionalProperties"])

    def test_source_targets_preserve_plan_ratio_and_exact_total(self) -> None:
        self.assertEqual(allocate_source_targets(
            ["D1.1", "D1.2", "D2.1"], 101, {"D1.1": 1, "D1.2": 2, "D2.1": 1}),
            {"D1.1": 25, "D1.2": 51, "D2.1": 25})

    def test_planned_source_targets_sum_to_generation_target(self) -> None:
        beats = planned_draft_beats([
            {"beats": ["a", "b"]}, {"beats": ["c", "d", "e"]},
        ], 1980)
        self.assertEqual(sum(beat.target_characters for beat in beats), 1980)
        self.assertTrue(all(beat.target_characters > 0 for beat in beats))

    def test_long_target_gets_distinct_technical_developments_with_bounded_targets(self) -> None:
        beats = planned_draft_beats([{"beats": ["長い展開"]}], 7200, source_capacity=2500)
        self.assertGreater(len(beats), 1)
        self.assertEqual(sum(beat.target_characters for beat in beats), 7200)
        self.assertTrue(all(beat.chapter_index == 0 and beat.target_characters <= 900 for beat in beats))
        self.assertEqual(len({beat.text for beat in beats}), len(beats))

    def test_truncated_source_object_keeps_only_closed_preceding_sources(self) -> None:
        content = ('{"D1.1":{"lines":[{"speaker":"A","text":"保存する"}]},'
                   '"D1.2":{"lines":[{"speaker":"A","text":"捨てる')
        records, partial = extract_required_sources(content, ["D1.1", "D1.2"])
        self.assertTrue(partial)
        self.assertEqual(records, [{"speaker": "A", "text": "保存する", "source": "D1.1",
                                    "source_complete": True}])

    def test_packets_span_chapters_and_split_only_at_beats(self) -> None:
        chapters = [
            {"title": "一", "beats": ["導入", "発見"]},
            {"title": "二", "beats": ["対立", "決着"]},
        ]
        beats = planned_draft_beats(chapters, 6000)
        self.assertEqual(sum(beat.target_characters for beat in beats), 6000)
        self.assertTrue(all(400 <= beat.target_characters <= 900 for beat in beats))
        packets = build_draft_packets(beats)
        self.assertEqual(sum(len(packet) for packet in packets), len(beats))
        self.assertEqual([chapter["number"] for chapter in packet_chapters(packets[0], chapters)], [1, 2])

    def test_schema_preserves_sources_and_complete_records_on_truncation(self) -> None:
        request = DraftRequest(base_url="http://127.0.0.1:9999/v1", model="schema-model",
                               character_ids=["cast-a"], target_minutes=1, theme="二つの展開を続ける。")
        response = LlmContractResult(records=(
            {"source": "D1.1", "speaker": "A", "text": "最初の展開です。", "emoji": None,
             "rate": "1.0", "gap": "0.7", "direction": "静かに", "cue": None,
             "source_complete": True},
            {"source": "D1.2", "speaker": "A", "text": "次の展開です。", "emoji": None,
             "rate": "1.0", "gap": "0.7", "direction": "明るく", "cue": None,
             "source_complete": False},
        ), mode="schema", raw_response="", manifest=(),
            transport=LlmTransportResult(content="", partial=True))
        capabilities = {"structuredOutput": {"streaming": {"state": "schema_validated"}}}
        with patch("server.modules.llm_completion_service.complete_records", return_value=response) as completion, \
             patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value=capabilities):
            dialogue, reason = generate_draft_dialogue(
                request, cast_context=[{"cast": "A", "name": "莉里"}],
                plan={"story_bible": "", "chapters": []},
                chapter={"title": "章", "beats": ["D1.1|導入", "D1.2|決断"]}, chapter_index=0,
                requested_characters=320, remaining_characters=320, accepted_dialogue={"lines": []},
                continuity_state="", completion_ledger={
                    "completed_sources": [{"source_id": "D0.1", "development": "入店する"}],
                    "completed_chapters": [1],
                    "confirmed_closing_states": [{"chapter": 1, "state": "注文を終えた"}],
                }, token_budget=6144, cast_alias_by_id={"cast-a": "A"})
        self.assertIsNone(reason)
        self.assertTrue(dialogue["_partial"])
        self.assertEqual([line["development_id"] for line in dialogue["lines"]], ["D1.1", "D1.2"])
        self.assertTrue(dialogue["lines"][0]["source_complete"])
        self.assertNotIn("source_complete", dialogue["lines"][1])
        contract = completion.call_args.kwargs["contract"]
        self.assertEqual(contract.owner_key, "source")
        self.assertEqual(contract.aliases, frozenset({"D1.1", "D1.2"}))
        self.assertEqual(contract.response_schema["required"], ["D1.1", "D1.2"])
        self.assertFalse(contract.response_schema["additionalProperties"])
        system = completion.call_args.kwargs["system"]
        self.assertIn('"D1.1"', system)
        self.assertNotIn("JSON、Markdown", system)
        self.assertIn("再演、再導入", system)
        user = completion.call_args.kwargs["user"]
        ledger = next(section["completion_ledger"] for section in user["sections"]
                      if "completion_ledger" in section)
        self.assertEqual(ledger["completed_sources"][0]["development"], "入店する")
        self.assertEqual(ledger["confirmed_closing_states"][0]["state"], "注文を終えた")

    def test_schema_detaches_json_direction_fields_leaked_into_text(self) -> None:
        request = DraftRequest(base_url="http://127.0.0.1:9999/v1", model="schema-model",
                               character_ids=["cast-a"], target_minutes=1, theme="激辛料理を食べる。")
        response = LlmContractResult(records=({
            "source": "D1.1", "speaker": "A",
            "text": 'げっ、激辛！ええなあ！俺も刺激的なもんは大好きや！","emoji":"@激辛","rate":"1.10',
            "emoji": None, "rate": None, "gap": None, "direction": None, "cue": None,
            "source_complete": True,
        },), mode="schema", raw_response="", manifest=(),
            transport=LlmTransportResult(content=""))
        capabilities = {"structuredOutput": {"streaming": {"state": "schema_validated"}}}
        with patch("server.modules.llm_completion_service.complete_records", return_value=response), \
             patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value=capabilities):
            dialogue, reason = generate_draft_dialogue(
                request, cast_context=[{"cast": "A", "name": "橘"}],
                plan={"story_bible": "", "chapters": []},
                chapter={"title": "章", "beats": ["D1.1|激辛料理を食べる"]}, chapter_index=0,
                requested_characters=160, remaining_characters=160, accepted_dialogue={"lines": []},
                continuity_state="", token_budget=4096, cast_alias_by_id={"cast-a": "A"})
        self.assertIsNone(reason)
        self.assertEqual(dialogue["lines"][0]["text"],
                         "げっ、激辛！ええなあ！俺も刺激的なもんは大好きや！")
        self.assertEqual(dialogue["lines"][0]["integrated_direction"],
                         {"emoji": "@激辛", "rate": "1.10"})

    def test_schema_cleans_mixed_quote_tails_without_overwriting_sibling_fields(self) -> None:
        request = DraftRequest(base_url="http://127.0.0.1:9999/v1", model="schema-model",
                               character_ids=["cast-a"], target_minutes=1, theme="驚く。")
        records = tuple({
            "source": "D1.1", "speaker": "A",
            "text": f'あーっ！その{index}」「emoji":"😱@あーっ」「rate":"1.15」「gap":"0.20',
            "emoji": "😊@あーっ", "rate": "0.95", "gap": "0.70",
            "direction": "驚いて", "cue": "NORMAL", "source_complete": index == 13,
        } for index in range(1, 14))
        response = LlmContractResult(records=records, mode="schema", raw_response="", manifest=(),
            transport=LlmTransportResult(content=""))
        capabilities = {"structuredOutput": {"streaming": {"state": "schema_validated"}}}
        with patch("server.modules.llm_completion_service.complete_records", return_value=response) as completion, \
             patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value=capabilities):
            dialogue, reason = generate_draft_dialogue(
                request, cast_context=[{"cast": "A", "name": "橘"}],
                plan={"story_bible": "", "chapters": []},
                chapter={"title": "章", "beats": ["D1.1|驚く"]}, chapter_index=0,
                requested_characters=320, remaining_characters=320, accepted_dialogue={"lines": []},
                continuity_state="", token_budget=4096, cast_alias_by_id={"cast-a": "A"})
        self.assertIsNone(reason)
        self.assertEqual(len(dialogue["lines"]), 13)
        self.assertTrue(all("emoji" not in line["text"] and "rate" not in line["text"]
                            for line in dialogue["lines"]))
        self.assertTrue(all(line["integrated_direction"] == {
            "emoji": "😊@あーっ", "rate": "0.95", "gap": "0.70",
            "direction": "驚いて", "cue": "NORMAL",
        } for line in dialogue["lines"]))
        self.assertIn("兄弟プロパティを複写しない", completion.call_args.kwargs["system"])

    def test_non_schema_model_keeps_adaptive_continuity_with_single_source_legacy_output(self) -> None:
        request = DraftRequest(base_url="http://127.0.0.1:9999/v1", model="plain-model",
                               character_ids=["cast-a"], target_minutes=1, theme="続きを話す。")
        response = LlmContractResult(records=(
            {"speaker": "A", "text": "雨が上がったから、先へ進もう。", "emoji": None,
             "rate": "1.0", "gap": "0.7", "direction": "前向きに", "cue": "NORMAL"},
        ), mode="legacy", raw_response="", manifest=(), transport=LlmTransportResult(content=""))
        capabilities = {"structuredOutput": {"streaming": {"state": "unsupported"}}}
        with patch("server.modules.llm_completion_service.complete_records", return_value=response) as completion, \
             patch("server.modules.llm_registry_metadata.resolve_llm_capabilities", return_value=capabilities):
            dialogue, reason = generate_draft_dialogue(
                request, cast_context=[{"cast": "A", "name": "莉里"}],
                plan={"story_bible": "", "chapters": []},
                chapter={"title": "章", "beats": ["D2.1|雨上がりに出発する"]}, chapter_index=1,
                requested_characters=240, remaining_characters=240,
                accepted_dialogue={"lines": [{"character_id": "cast-a", "text": "雨が弱くなってきたね。"}]},
                continuity_state="店を出る準備をした", completion_ledger={
                    "completed_sources": [{"source_id": "D1.1", "development": "注文と食事を終える"}],
                    "completed_chapters": [1],
                    "confirmed_closing_states": [{"chapter": 1, "state": "食事を終えた"}],
                }, token_budget=4096, cast_alias_by_id={"cast-a": "A"})
        self.assertIsNone(reason)
        self.assertEqual(dialogue["_contract_mode"], "legacy")
        self.assertEqual(dialogue["lines"][0]["text"], "雨が上がったから、先へ進もう。")
        self.assertIn("一発話一行", completion.call_args.kwargs["system"])
        user = completion.call_args.kwargs["user"]
        ledger = next(section["completion_ledger"] for section in user["sections"]
                      if "completion_ledger" in section)
        self.assertEqual(ledger["completed_sources"][0]["source_id"], "D1.1")
        accepted = next(section["accepted_dialogue_and_current_request"] for section in user["sections"]
                        if "accepted_dialogue_and_current_request" in section)
        self.assertEqual(accepted["accepted_dialogue_so_far"]["resent_recent_line_count"], 1)


if __name__ == "__main__":
    unittest.main()
