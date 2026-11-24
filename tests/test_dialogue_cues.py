import unittest

from server.modules.dialogue_cues import (
    cue_groups,
    linked_cue_target_duration,
    normalize_scene_cues,
    normalize_target_duration,
)


def line(line_id: str, cast: str, cue: str | None = None, **extra):
    value = {"id": line_id, "characterId": cast, "text": line_id, "takes": [], **extra}
    if cue is not None:
        value["cueId"] = cue
    return value


class DialogueCueTests(unittest.TestCase):
    def test_finalizes_draft_candidate_with_zero_offsets_and_tail_gap_on_head(self) -> None:
        from server.app import finalize_draft_simultaneous_cues
        lines = [
            line("a", "a", simultaneous_candidate_id="draft", gapSeconds=0.2),
            line("b", "b", simultaneous_candidate_id="draft", gapSeconds=1.4),
        ]
        self.assertEqual(finalize_draft_simultaneous_cues(lines), 1)
        self.assertEqual(lines[0]["gapSeconds"], 1.4)
        self.assertNotIn("gapSeconds", lines[1])
        self.assertEqual({item["startOffsetSeconds"] for item in lines}, {0.0})
        self.assertEqual(len({item["cueId"] for item in lines}), 1)
    def test_normalize_keeps_valid_consecutive_group_and_shared_state_on_head(self):
        scene = {"lines": [line("a", "one", "cue", enabled=False, gapSeconds=2), line("b", "two", "cue", enabled=True, gapSeconds=9, startOffsetSeconds=-2)]}
        normalize_scene_cues(scene)
        self.assertEqual(len(cue_groups(scene["lines"])), 1)
        self.assertEqual(scene["lines"][1]["startOffsetSeconds"], 0)
        self.assertNotIn("enabled", scene["lines"][1])
        self.assertNotIn("gapSeconds", scene["lines"][1])

    def test_normalize_dissolves_nonconsecutive_and_singleton_without_losing_content(self):
        scene = {"lines": [line("a", "one", "broken"), line("middle", "three"), line("b", "two", "broken"), line("single", "four", "solo")]}
        normalize_scene_cues(scene)
        self.assertEqual([item["text"] for item in scene["lines"]], ["a", "middle", "b", "single"])
        self.assertTrue(all("cueId" not in item for item in scene["lines"]))

    def test_duplicate_cast_is_split_and_valid_siblings_are_preserved(self):
        scene = {"lines": [line("a", "one", "cue"), line("b", "one", "cue"), line("c", "two", "cue")]}
        normalize_scene_cues(scene)
        self.assertTrue(all("cueId" not in item for item in scene["lines"]))
        self.assertEqual([item["text"] for item in scene["lines"]], ["a", "b", "c"])

    def test_manual_target_duration_is_kept_on_any_group_member(self):
        scene = {"lines": [
            line("a", "one", "cue", targetDurationSeconds=9),
            line("b", "two", "cue", targetDurationSeconds=5.54, speechRate=0.8),
        ]}
        normalize_scene_cues(scene)
        self.assertEqual(scene["lines"][0]["targetDurationSeconds"], 9.0)
        self.assertEqual(scene["lines"][1]["targetDurationSeconds"], 5.5)
        self.assertEqual(scene["lines"][1]["speechRate"], 0.8)

    def test_target_duration_normalizes_boundaries_and_invalid_values(self):
        self.assertEqual(normalize_target_duration(0.1), 0.5)
        self.assertEqual(normalize_target_duration(99), 30.0)
        self.assertIsNone(normalize_target_duration("invalid"))
        self.assertIsNone(normalize_target_duration(float("nan")))

    def test_dissolving_a_cue_keeps_manual_target_duration_for_the_regular_line(self):
        scene = {"lines": [line("a", "one", "cue", targetDurationSeconds=5.5)]}
        normalize_scene_cues(scene)
        self.assertEqual(scene["lines"][0]["targetDurationSeconds"], 5.5)

    def test_linked_duration_uses_the_earliest_other_selected_take_and_relative_rate(self):
        first = line("a", "one", "cue", selectedTakeId="take-a")
        first["takes"] = [{"id": "take-a", "durationSeconds": 5.5, "createdAt": 20, "settings": {"speechRate": 1.1}}]
        earlier = line("b", "two", "cue", selectedTakeId="take-b")
        earlier["takes"] = [{"id": "take-b", "durationSeconds": 4.0, "createdAt": 10, "settings": {"speechRate": 1.0}}]
        target = line("c", "three", "cue")
        project = {"scenes": [{"lines": [first, earlier, target]}]}
        self.assertEqual(linked_cue_target_duration(project, target, 0.8), 5.0)

    def test_linked_duration_excludes_the_line_being_regenerated(self):
        target = line("a", "one", "cue", selectedTakeId="take-a")
        target["takes"] = [{"id": "take-a", "durationSeconds": 8, "createdAt": 1, "settings": {"speechRate": 1.0}}]
        basis = line("b", "two", "cue", selectedTakeId="take-b")
        basis["takes"] = [{"id": "take-b", "durationSeconds": 4, "createdAt": 2, "settings": {"speechRate": 1.0}}]
        project = {"scenes": [{"lines": [target, basis]}]}
        self.assertEqual(linked_cue_target_duration(project, target, 1.0), 4.0)
