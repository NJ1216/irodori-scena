"""Dialogue acceptance is independent of enclosing JSON completion."""
import json
import unittest

from server.app import extract_required_sources, normalize_draft_dialogue


class PartialDialogueTests(unittest.TestCase):
    def test_malformed_scalar_preserves_valid_text_and_other_fields(self):
        raw = '{"D1":{"lines":[{"speaker":"A","text":"保持","rate":1oops,"gap":0.7}]}}'
        rows, partial = extract_required_sources(raw, ["D1"])
        self.assertFalse(partial)
        self.assertEqual(rows, [{"speaker": "A", "text": "保持", "gap": 0.7,
                                 "source": "D1", "source_complete": True}])

    def test_closed_text_survives_cut_direction_and_scene(self):
        raw = '{"D1.1":{"lines":[{"speaker":"A","text":"残す。","direction":"途中'
        rows, partial = extract_required_sources(raw, ["D1.1"])
        self.assertTrue(partial)
        self.assertEqual(rows, [{"speaker": "A", "text": "残す。", "source": "D1.1"}])

    def test_bad_siblings_duplicates_and_json_looking_text(self):
        text = '引用「{\"speaker\":\"B\",\"text\":\"偽物\"}」\n\\[]'
        raw = ('{"D1.1":{"lines":[invalid,{"speaker":"A","text":' + json.dumps(text) +
               '},null,{"speaker":"A","text":"次"}]},'
               '"D1.1":{"lines":[{"speaker":"B","text":"上書き禁止"}]},'
               '"unknown":{"lines":[{"speaker":"A","text":"対象外"}]},'
               '"D1.2":{"lines":[{"speaker":"A","text":"最後"}]}}')
        rows, partial = extract_required_sources(raw, ["D1.1", "D1.2"])
        self.assertEqual([r["text"] for r in rows], [text, "次", "最後"])
        self.assertFalse(partial)

    def test_all_prefixes_preserve_published_text_and_do_not_guess_strings(self):
        raw = '{"D1.1":{"lines":[{"speaker":"A","text":"改行\\n引用\\\"括弧}"},{"speaker":"A","text":"二行目"}]}}'
        previous = []
        for index in range(len(raw) + 1):
            rows, _ = extract_required_sources(raw[:index], ["D1.1"])
            identity = [(r.get("speaker"), r.get("text")) for r in rows]
            self.assertEqual(identity[:len(previous)], previous)
            self.assertTrue(all(pair in [("A", '改行\n引用"括弧}'), ("A", "二行目")] for pair in identity))
            previous = identity
        self.assertEqual(len(previous), 2)

    def test_invalid_duplicate_source_does_not_mask_a_later_usable_source(self):
        raw = '{"D1":null,"D1":{"lines":[]},"D1":{"lines":[{"speaker":"A","text":"保持"}]}}'
        rows, partial = extract_required_sources(raw, ["D1"])
        self.assertEqual([r["text"] for r in rows], ["保持"])
        self.assertFalse(partial)

    def test_semantic_incompletion_is_independent_of_closed_braces(self):
        raw = '{"D1":{"lines":[{"speaker":"A","text":"途中"}],"complete":false}}'
        rows, partial = extract_required_sources(raw, ["D1"])
        self.assertTrue(partial)
        self.assertEqual(rows[0]["text"], "途中")
        self.assertNotIn("source_complete", rows[0])

    def test_unknown_solo_speaker_is_not_reassigned_and_emoji_sibling_survives(self):
        raw = {"lines": [{"character_id": "UNKNOWN", "text": "不明"},
                         {"character_id": "A", "text": "本文😊🚫"}]}
        result = normalize_draft_dialogue(raw, permitted={"cast-a"}, character_name_to_id={"A": "cast-a"},
                                          chapter_index=0)
        self.assertEqual([r["text"] for r in result["lines"]], ["本文"])


if __name__ == "__main__":
    unittest.main()
