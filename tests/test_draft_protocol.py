from __future__ import annotations

import scena_test_isolation  # noqa: F401
import server.app  # noqa: F401  (registers the backend dependencies these modules read)
import unittest

from server.draft_protocol import (
    parse_context_selection,
    parse_dialogue_protocol,
    parse_performance_protocol,
    parse_plan_protocol,
)


class DraftProtocolTests(unittest.TestCase):
    def test_plan_keeps_chapter_cast_ownership_and_required_profile_fields(self) -> None:
        parsed = parse_plan_protocol(
            "TITLE|待ち合わせ\nSTORY|駅で会う\nCHAPTER|1|到着\n"
            "SPEAKING_CAST|A\nMENTIONED_CAST|C\nREQUIRED_PROFILE|C|background\n"
            "OBJECTIVE|合流する\nBEAT|Aが到着する\nEND_CHAPTER"
        )
        chapter = parsed["chapters"][0]
        self.assertEqual(chapter["speaking_casts"], ["A"])
        self.assertEqual(chapter["mentioned_casts"], ["C"])
        self.assertEqual(chapter["required_profile_fields"], {"C": ["background"]})

    def test_context_selection_ignores_unknown_values(self) -> None:
        selected = parse_context_selection(
            "NEED|cast-a|hobbies\nNEED|cast-a|secret\nNEED|cast-x|hobbies",
            allowed_cast_ids={"cast-a"},
            allowed_fields={"hobbies"},
        )
        self.assertEqual(selected, {"cast-a": {"hobbies"}})

    def test_context_selection_accepts_short_cast_alias(self) -> None:
        selected = parse_context_selection(
            "A|hobbies\nB:relationships\nNONE",
            allowed_cast_ids={"A", "B"},
            allowed_fields={"hobbies", "relationships"},
        )
        self.assertEqual(selected, {"A": {"hobbies"}, "B": {"relationships"}})

    def test_plan_protocol_keeps_multiple_beats(self) -> None:
        plan = parse_plan_protocol(
            """TITLE|放課後の約束
STORY|二人が誤解を解く。
CHAPTER|1|教室
OBJECTIVE|話を切り出す
OPENING|沈黙している
BEAT|窓の外を見る
BEAT|謝る
CLOSING|返事を待つ
NOVELTY|本音を初めて話す
CONTINUITY|呼び方を守る
END_CHAPTER"""
        )
        self.assertEqual(plan["title"], "放課後の約束")
        self.assertEqual(plan["chapters"][0]["beats"], ["窓の外を見る", "謝る"])

    def test_plan_protocol_keeps_reader_facing_cast_description(self) -> None:
        plan = parse_plan_protocol(
            """TITLE|配信のあとで
CAST_CONTEXT|A|配信者（VTuber）|明るく率直なVTuber。リスナーとの距離が近い。
CHAPTER|1|配信終了後
OBJECTIVE|余韻を共有する
BEAT|コメントを振り返る
END_CHAPTER"""
        )
        self.assertEqual(plan["cast_contexts"], {
            "A": {
                "role": "配信者（VTuber）",
                "description": "明るく率直なVTuber。リスナーとの距離が近い。",
            }
        })

    def test_plan_protocol_collects_unlabelled_lines_inside_beat_section(self) -> None:
        plan = parse_plan_protocol(
            """TITLE|数学の授業
STORY|授業中の出来事。
CHAPTER|1|静寂の教室
OBJECTIVE|Ririが問題に向き合う
BEAT|少佐が黒板に数式を書く
Ririが数式を見て焦る
3. 紗良が隣から様子をうかがう
CLOSING|Ririが指名される
この行はCLOSING後なのでビートではない
END_CHAPTER"""
        )
        self.assertEqual(
            plan["chapters"][0]["beats"],
            ["少佐が黒板に数式を書く", "Ririが数式を見て焦る", "紗良が隣から様子をうかがう"],
        )

    def test_dialogue_protocol_assigns_stable_ids(self) -> None:
        result = parse_dialogue_protocol(
            """::LINE L001 cast-a
TEXT|おはよう。
::END
::LINE L002 cast-b
TEXT|今日は早いね。
::END"""
        )
        self.assertEqual([line["line_id"] for line in result["lines"]], ["L001", "L002"])

    def test_dialogue_protocol_preserves_text_when_model_repeats_ids(self) -> None:
        result = parse_dialogue_protocol(
            """::LINE L001 cast-a
TEXT|最初の台詞。
::END
::LINE L001 cast-b
TEXT|次の台詞。| ::END"""
        )
        self.assertEqual([line["text"] for line in result["lines"]], ["最初の台詞。", "次の台詞。"])

    def test_dialogue_protocol_accepts_app_assigned_id_format(self) -> None:
        result = parse_dialogue_protocol("::LINE cast-a\nTEXT|続きだけを書く。\n::END")
        self.assertEqual(result["lines"][0]["character_id"], "cast-a")

    def test_dialogue_protocol_accepts_one_line_aliases_and_common_variants(self) -> None:
        result = parse_dialogue_protocol(
            """A|最初の台詞。
B: 次の台詞。
::LINE_A
TEXT|三つ目の台詞。
::END""",
            allowed_speakers={"A", "B"},
        )
        self.assertEqual(
            [(line["character_id"], line["text"]) for line in result["lines"]],
            [("A", "最初の台詞。"), ("B", "次の台詞。"), ("A", "三つ目の台詞。")],
        )

    def test_dialogue_protocol_salvages_integrated_direction_fields_independently(self) -> None:
        result = parse_dialogue_protocol(
            "A|おはよう。||unknown=x|rate=0.96|emoji=😌@おはよう|rate=bad|direction=穏やかに\n"
            "B|途中まで||gap=-0.20|cue=SIM:S1",
            allowed_speakers={"A", "B"},
        )
        first, second = result["lines"]
        self.assertEqual(first["text"], "おはよう。")
        self.assertEqual(first["integrated_direction"], {
            "rate": "0.96", "emoji": "😌@おはよう", "direction": "穏やかに",
        })
        self.assertEqual(second["text"], "途中まで")
        self.assertEqual(second["integrated_direction"], {"gap": "-0.20", "cue": "SIM:S1"})

    def test_repeated_field_boundary_does_not_leak_pipe_into_emoji_or_direction(self) -> None:
        parsed = parse_dialogue_protocol(
            "A|おはよう。||emoji=😊@おはよう||rate=0.95|direction=明るく||cue=SIM:S1",
            allowed_speakers={"A"},
        )
        values = parsed["lines"][0]["integrated_direction"]
        self.assertEqual(values["emoji"], "😊@おはよう")
        self.assertEqual(values["rate"], "0.95")
        self.assertEqual(values["direction"], "明るく")
        self.assertEqual(values["cue"], "SIM:S1")

    def test_dialogue_protocol_recovers_leaked_inline_emoji_anchor_without_spoken_control_text(self) -> None:
        result = parse_dialogue_protocol(
            "A|それこそいつもの感じやな！😆@感じ||emoji=😆|rate=1.20\n"
            "B|あたしも混ぜてよ！👌@混ぜて||emoji=👌|direction=割り込むように",
            allowed_speakers={"A", "B"},
        )
        first, second = result["lines"]
        self.assertEqual(first["text"], "それこそいつもの感じやな！")
        self.assertEqual(first["integrated_direction"]["emoji"], "😆@感じ")
        self.assertEqual(second["text"], "あたしも混ぜてよ！")
        self.assertEqual(second["integrated_direction"]["emoji"], "👌@混ぜて")

    def test_dialogue_protocol_recovers_json_direction_tail_from_spoken_text(self) -> None:
        result = parse_dialogue_protocol(
            'NORMAL|A|げっ、激辛！ええなあ！俺も刺激的なもんは大好きや！","emoji":"@激辛","rate":"1.10',
            allowed_speakers={"A"},
        )
        line = result["lines"][0]
        self.assertEqual(line["text"], "げっ、激辛！ええなあ！俺も刺激的なもんは大好きや！")
        self.assertEqual(line["integrated_direction"], {"emoji": "@激辛", "rate": "1.10"})

    def test_dialogue_protocol_recovers_mixed_quote_json_direction_tail(self) -> None:
        tails = (
            '」「emoji":"😱@あーっ」「rate":"1.15',
            '、「emoji」:「😱@あーっ」、「rate」:「1.15」',
        )
        for tail in tails:
            with self.subTest(tail=tail):
                result = parse_dialogue_protocol(f"NORMAL|A|あーっ！…{tail}", allowed_speakers={"A"})
                line = result["lines"][0]
                self.assertEqual(line["text"], "あーっ！…")
                self.assertEqual(line["integrated_direction"], {"emoji": "😱@あーっ", "rate": "1.15"})

    def test_dialogue_protocol_preserves_two_ordinary_quoted_field_names(self) -> None:
        text = "設定では「emoji」や「rate」という語を使う。"
        result = parse_dialogue_protocol(f"A|{text}", allowed_speakers={"A"})
        self.assertEqual(result["lines"][0]["text"], text)

    def test_dialogue_protocol_preserves_a_single_json_like_phrase(self) -> None:
        result = parse_dialogue_protocol('A|設定名は"rate":"高速"だよ。', allowed_speakers={"A"})
        self.assertEqual(result["lines"][0]["text"], '設定名は"rate":"高速"だよ。')

    def test_dialogue_protocol_preserves_ordinary_at_text(self) -> None:
        result = parse_dialogue_protocol(
            "A|連絡先はuser@example.comだよ。||rate=1.00",
            allowed_speakers={"A"},
        )
        self.assertEqual(result["lines"][0]["text"], "連絡先はuser@example.comだよ。")

    def test_dialogue_protocol_accepts_an_allowed_display_name(self) -> None:
        result = parse_dialogue_protocol("Riri|こんばんは！", allowed_speakers={"A", "Riri"})
        self.assertEqual(result["lines"][0]["character_id"], "Riri")

    def test_dialogue_protocol_parses_simultaneous_marker_without_leaking_control_text(self) -> None:
        result = parse_dialogue_protocol(
            "A|SIM:S1|せーの！\nB|SIM:S1|いくよ！\nC|SIM:bad marker|本文は残す。",
            allowed_speakers={"A", "B", "C"},
        )
        self.assertEqual([line["text"] for line in result["lines"]], ["せーの！", "いくよ！", "本文は残す。"])
        self.assertEqual([line.get("simultaneous_marker") for line in result["lines"]], ["S1", "S1", None])

    def test_dialogue_protocol_v2_keeps_normal_lead_in_outside_different_simultaneous_texts(self) -> None:
        result = parse_dialogue_protocol(
            "NORMAL|A|せーの！||rate=1.00|direction=合図する\n"
            "SIM:S1|A|やっほ〜！||rate=1.10|direction=明るく\n"
            "SIM:S1|B|こんにちは！||rate=0.95|direction=朗らかに",
            allowed_speakers={"A", "B"},
        )
        lead_in, first, second = result["lines"]
        self.assertNotIn("cue", lead_in["integrated_direction"])
        self.assertEqual(first["integrated_direction"]["cue"], "SIM:S1")
        self.assertEqual(second["integrated_direction"]["cue"], "SIM:S1")
        self.assertEqual([first["text"], second["text"]], ["やっほ〜！", "こんにちは！"])

    def test_dialogue_protocol_v2_discards_only_invalid_cue_marker(self) -> None:
        result = parse_dialogue_protocol(
            "SIM:bad marker|A|本文は残す。||rate=1.05|direction=明るく",
            allowed_speakers={"A"},
        )
        line = result["lines"][0]
        self.assertEqual(line["text"], "本文は残す。")
        self.assertEqual(line["integrated_direction"], {"rate": "1.05", "direction": "明るく"})

    def test_dialogue_protocol_maps_all_aliases_to_the_one_selected_cast(self) -> None:
        result = parse_dialogue_protocol(
            "A|最初の台詞。\nB|続きの台詞。\nC|最後の台詞。",
            speaker_aliases={"A": "A", "Riri": "A", "character-a": "A"},
        )
        self.assertEqual([line["character_id"] for line in result["lines"]], ["A", "A", "A"])

    def test_dialogue_protocol_retains_an_overlong_record_unchanged(self) -> None:
        first = "長い説明です。" * 30
        second = "次の文も同じ話者の発話です！"
        result = parse_dialogue_protocol(f"A|{first}{second}", allowed_speakers={"A"})
        self.assertEqual(len(result["lines"]), 1)
        self.assertEqual(result["lines"][0]["text"], f"{first}{second}")

    def test_dialogue_protocol_recovers_literal_escaped_record_separators(self) -> None:
        result = parse_dialogue_protocol(
            r"C|最初の台詞。\nA|次の台詞。\nB|……。",
            allowed_speakers={"A", "B", "C"},
        )
        self.assertEqual(
            [(line["character_id"], line["text"]) for line in result["lines"]],
            [("C", "最初の台詞。"), ("A", "次の台詞。"), ("B", "……。")],
        )

    def test_dialogue_protocol_salvages_observed_bare_application_id(self) -> None:
        result = parse_dialogue_protocol(
            "::character_c3e0e4d32131\nTEXT|少佐の台詞。| ::END",
            allowed_speakers={"character_c3e0e4d32131"},
        )
        self.assertEqual(result["lines"][0]["text"], "少佐の台詞。")

    def test_performance_and_transition_are_separate_records(self) -> None:
        result = parse_performance_protocol(
            """::PERFORMANCE L001
PERFORMED_TEXT|😊おはよう。
DIRECTION|相手を安心させるように
SPEECH_RATE|0.98
::END
::TRANSITION L001 L002
GAP_SECONDS|0.72
INTENT|すぐ返事を受ける
::END"""
        )
        self.assertEqual(result["performances"]["L001"]["speech_rate"], "0.98")
        self.assertEqual(result["transitions"]["L001->L002"]["gap_seconds"], "0.72")

    def test_performance_accepts_one_line_acting_record(self) -> None:
        result = parse_performance_protocol("L1|0.98|0.72|相手を安心させるように|😊おはよう……。")
        self.assertEqual(result["performances"]["L1"]["speech_rate"], "0.98")
        self.assertEqual(result["performances"]["L1"]["performed_text"], "😊おはよう……。")
        self.assertEqual(result["transitions"]["L1->NEXT"]["gap_seconds"], "0.72")


if __name__ == "__main__":
    unittest.main()
