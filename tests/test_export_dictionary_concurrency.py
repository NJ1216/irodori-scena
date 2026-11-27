from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from server.app import app as _registered_app  # noqa: F401
from server.modules import constants, project_repository, script_routes
from server.modules.export_service import ensure_export_take


def entry(entry_id: str, term: str, reading: str = "よみ", origin: str = "manual") -> dict:
    return {"id": entry_id, "term": term, "reading": reading, "source": "manual", "projectScopeOrigin": origin}


class ExportDictionaryConcurrencyTests(unittest.TestCase):
    def setUp(self) -> None:
        root = Path(self.enterContext(TemporaryDirectory()))
        for name, value in {"ACTIVE_PROJECT_ROOT": root, "PROJECT_FILE": root / "project.json", "MEDIA_ROOT": root / "media", "ACTIVE_PROJECT_PATH": None}.items():
            self.enterContext(patch.object(constants, name, value))
        self.enterContext(patch.object(project_repository, "resolved_project_characters", side_effect=lambda value: value))
        self.enterContext(patch("server.modules.pronunciation_dictionary.read_pronunciation_dictionary", return_value=[]))
        self.project = json.loads((Path(__file__).parent / "fixtures/project-contract.json").read_text())
        line = self.project["scenes"][0]["lines"][0]
        self.take = line["takes"][0]
        line.update(takes=[], selectedTakeId=None)
        self.project["pronunciationDictionary"] = [entry("old", "旧項目"), entry("remove", "削除対象")]
        project_repository.write_project(self.project)

    def complete_with_edit(self, edit, promoted=None):
        def render(project, *_args, **_kwargs):
            latest = project_repository.read_project()
            edit(latest["pronunciationDictionary"])
            project_repository.write_project(latest)
            if promoted:
                project["pronunciationDictionary"].append(promoted)
            return self.take

        with patch.object(script_routes, "create_line_take", side_effect=render):
            ensure_export_take("line_contract", "fast", should_cancel=lambda: False)
        return project_repository.read_project()["pronunciationDictionary"]

    def test_generation_preserves_concurrent_additions_edits_and_deletions(self) -> None:
        def edit(entries):
            entries[0].update(reading="あたらしいよみ", locked=True)
            entries.pop(1)
            entries.append(entry("new", "追加項目"))

        saved = self.complete_with_edit(edit)
        self.assertEqual([item["id"] for item in saved], ["old", "new"])
        self.assertEqual(saved[0]["reading"], "あたらしいよみ")
        self.assertTrue(saved[0]["locked"])

    def test_generation_adds_only_new_promotions_without_restoring_removed_entries(self) -> None:
        promoted = entry("promoted", "生成で使用", origin="script-auto")
        saved = self.complete_with_edit(lambda entries: entries.clear(), promoted)
        self.assertEqual(saved, [promoted])

    def test_concurrent_manual_choice_wins_over_promotion_for_same_term(self) -> None:
        promoted = entry("promoted", "SCENA", "しーな", "script-auto")
        manual = entry("user-choice", "scena", "せな")
        saved = self.complete_with_edit(lambda entries: entries.append(manual), promoted)
        self.assertEqual(saved, [*self.project["pronunciationDictionary"], manual])


if __name__ == "__main__":
    unittest.main()
