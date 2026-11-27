from __future__ import annotations

import scena_test_isolation  # noqa: F401
import base64
import copy
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import (
    ai_direction,
    candidate_clear_routes,
    draft_job_state,
    cast_sync,
    character_avatar_routes,
    character_routes,
    constants,
    history,
    project_repository,
    project_routes,
    pronunciation_dictionary,
    script_line_deletion_routes,
    script_routes,
)
from server.registry import deps

_PAUSE_SECONDS = 0.3


def _line(line_id: str, character_id: str) -> dict[str, Any]:
    take = {"id": f"take-{line_id}", "characterId": character_id, "audioUrl": f"/media/takes/{line_id}/take-{line_id}.wav"}
    return {"id": line_id, "characterId": character_id, "text": "台詞", "stageDirection": "", "takes": [take],
            "selectedTakeId": take["id"]}


def _project() -> dict[str, Any]:
    return {
        "title": "original", "revision": 0, "settings": {}, "candidates": [{"id": "candidate", "file": ""}],
        "characters": [{"id": "a", "name": "A"}, {"id": "b", "name": "B"}],
        "scenes": [
            {"id": "s1", "title": "S1", "lines": [_line("l1", "a"), _line("l2", "b")]},
            {"id": "s2", "title": "S2", "lines": [_line("l3", "a")]},
        ],
    }


class _Store:
    """In-memory project and cast library whose first handler read pauses."""

    def __init__(self, global_characters: list[dict[str, Any]] | None = None) -> None:
        self.project = _project()
        self.global_characters = copy.deepcopy(global_characters or [])
        self.pause_thread: int | None = None
        self.paused = threading.Event()
        self.resume = threading.Event()

    def _pause_once(self) -> None:
        if threading.get_ident() == self.pause_thread and not self.paused.is_set():
            self.paused.set()
            self.resume.wait(_PAUSE_SECONDS)

    def read_project(self) -> dict[str, Any]:
        snapshot = copy.deepcopy(self.project)
        self._pause_once()
        return snapshot

    def write_project(self, project: dict[str, Any], **_: Any) -> dict[str, Any]:
        with deps.PROJECT_ROOT_LOCK:
            project["revision"] = self.project["revision"] + 1
            self.project = copy.deepcopy(project)
            return copy.deepcopy(project)

    def read_global_characters(self) -> list[dict[str, Any]]:
        snapshot = copy.deepcopy(self.global_characters)
        self._pause_once()
        return snapshot

    def write_global_characters(self, characters: list[dict[str, Any]]) -> None:
        self.global_characters = copy.deepcopy(characters)


def _background_project_writer(store: _Store) -> None:
    # The pattern used by export take commits and auto-render generate commits.
    with deps.PROJECT_ROOT_LOCK:
        latest = store.read_project()
        latest["title"] = "background"
        store.write_project(latest)


def _background_cast_writer(store: _Store) -> None:
    with deps.PROJECT_ROOT_LOCK, deps.GLOBAL_CHARACTERS_LOCK:
        library = store.read_global_characters()
        store.write_global_characters([*library, {"id": "background-cast", "name": "BG"}])
        latest = store.read_project()
        latest["title"] = "background"
        store.write_project(latest)


def _lines(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {line["id"]: line for scene in project["scenes"] for line in scene["lines"]}


def _wav() -> bytes:
    return b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\0" * 32


def _rollback_draft_job() -> None:
    job_id = "draft-locking-test"
    deps.DRAFT_JOBS[job_id] = {"appendedSceneIds": ["s2"], "title": "", "previousTitle": ""}
    try:
        draft_job_state.rollback_cancelled_draft(job_id)
    finally:
        deps.DRAFT_JOBS.pop(job_id, None)


def _lock_is_free_for_other_threads() -> bool:
    outcome: list[bool] = []

    def probe() -> None:
        acquired = deps.PROJECT_ROOT_LOCK.acquire(blocking=False)
        outcome.append(acquired)
        if acquired:
            deps.PROJECT_ROOT_LOCK.release()

    thread = threading.Thread(target=probe)
    thread.start()
    thread.join(2)
    return outcome == [True]


class ProjectMutationLockingTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for target, value in (("MEDIA_ROOT", self.root / "media"), ("GLOBAL_MEDIA_ROOT", self.root / "global-media"),
                              ("ACTIVE_PROJECT_PATH", None)):
            patcher = patch.object(constants, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _race(self, store: _Store, handler: Callable[[], Any], background: Callable[[_Store], None]) -> None:
        errors: list[BaseException] = []

        def run_handler() -> None:
            store.pause_thread = threading.get_ident()
            try:
                handler()
            except BaseException as error:  # noqa: BLE001 - surfaced by the assertion below
                errors.append(error)

        def run_background() -> None:
            try:
                self.assertTrue(store.paused.wait(2), "handler never read the project")
                background(store)
            except BaseException as error:  # noqa: BLE001 - surfaced by the assertion below
                errors.append(error)
            finally:
                store.resume.set()

        with (
            patch("server.modules.project_repository.read_project", store.read_project),
            patch("server.modules.project_repository.write_project", store.write_project),
            patch("server.modules.project_repository.read_global_characters", store.read_global_characters),
            patch("server.modules.project_repository.write_global_characters", store.write_global_characters),
            patch("server.modules.export_service.require_tts_available", lambda **_: None),
        ):
            threads = [threading.Thread(target=run_handler), threading.Thread(target=run_background)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertFalse(any(thread.is_alive() for thread in threads), "writers deadlocked")
        self.assertEqual(errors, [])

    def test_project_handlers_do_not_lose_a_concurrent_locked_write(self) -> None:
        cases: list[tuple[str, Callable[[], Any], Callable[[dict[str, Any]], bool]]] = [
            ("delete_line", lambda: script_routes.delete_line("s1", "l1"), lambda p: "l1" not in _lines(p)),
            ("delete_scene", lambda: script_routes.delete_scene("s2"), lambda p: [s["id"] for s in p["scenes"]] == ["s1"]),
            ("add_cue_member", lambda: script_routes.add_cue_member("s1", "l1", SimpleNamespace(character_id="b")),
             lambda p: len(p["scenes"][0]["lines"]) == 3),
            ("delete_line_take", lambda: script_routes.delete_line_take("l1", "take-l1"), lambda p: _lines(p)["l1"]["takes"] == []),
            ("clear_all_takes", script_routes.clear_all_takes, lambda p: all(not line["takes"] for line in _lines(p).values())),
            ("cleanup_selected_takes", lambda: script_routes.cleanup_selected_takes({"line_ids": ["l1"], "mode": "all"}),
             lambda p: _lines(p)["l1"]["takes"] == []),
            ("delete_lines", lambda: script_line_deletion_routes.delete_lines({"line_ids": ["l2"]}), lambda p: "l2" not in _lines(p)),
            ("change_line_character", lambda: project_routes.change_line_character("l1", SimpleNamespace(character_id="b")),
             lambda p: _lines(p)["l1"]["characterId"] == "b"),
            ("switch_characters", lambda: project_routes.switch_characters(SimpleNamespace(
                mappings=[SimpleNamespace(from_character_id="a", to_character_id="b")])),
             lambda p: _lines(p)["l3"]["characterId"] == "b"),
            ("import_script", lambda: project_routes.import_script(SimpleNamespace(
                lines=[SimpleNamespace(character_id="a", text="読み込み")])), lambda p: len(p["scenes"]) == 3),
            ("clear_candidates", character_routes.clear_candidates, lambda p: p["candidates"] == []),
            ("ai_direction_apply", lambda: ai_direction._apply_updates(SimpleNamespace(
                overwrite_existing=True, remove_emoji_expressions=False, remove_speech_rate=False,
                remove_gap_seconds=False, remove_stage_direction=False), [{"id": "l1", "text": "演出後"}]),
             lambda p: _lines(p)["l1"]["text"] == "演出後"),
            ("delete_character_avatar", lambda: character_avatar_routes.delete_character_avatar("a"),
             lambda p: p["characters"][0]["id"] == "a"),
        ]
        for name, handler, applied in cases:
            with self.subTest(handler=name):
                store = _Store()
                self._race(store, handler, _background_project_writer)
                self.assertTrue(applied(store.project), f"{name} did not apply its own change")
                self.assertEqual(store.project["title"], "background", f"{name} overwrote a concurrent write")

    def test_candidate_clear_draft_rollback_and_first_save_do_not_lose_a_concurrent_write(self) -> None:
        destination = self.root / "saved.scena"
        first_save_patches = (
            patch("server.modules.project_repository.materialize_cast_global_characters", lambda project: project),
            patch("server.modules.workspace.require_external_project_destination"),
            patch("server.modules.project_container.working_root", return_value=self.root / "work"),
            patch("server.modules.project_container.sync_container"),
            patch("server.modules.project_container.container_signature", return_value=(1, 2, 3)),
            patch("server.modules.project_container.prepare_saved_workspace"),
            patch("server.modules.workspace.activate_project_container"),
            patch("server.modules.workspace.workspace_info", return_value={}),
        )

        def first_save() -> None:
            from contextlib import ExitStack
            with ExitStack() as stack:
                for item in first_save_patches:
                    stack.enter_context(item)
                project_repository.move_scratch_project_to(destination)

        cases: list[tuple[str, Callable[[], Any], Callable[[dict[str, Any]], bool]]] = [
            ("clear_candidate_scope", lambda: candidate_clear_routes.clear_candidate_scope("baseline"),
             lambda p: p["candidates"] == []),
            ("rollback_cancelled_draft", _rollback_draft_job, lambda p: [s["id"] for s in p["scenes"]] == ["s1"]),
            ("move_scratch_project_to", first_save, lambda p: p["revision"] == 2),
        ]
        for name, handler, applied in cases:
            with self.subTest(handler=name):
                store = _Store()
                self._race(store, handler, _background_project_writer)
                self.assertTrue(applied(store.project), f"{name} did not apply its own change")
                self.assertEqual(store.project["title"], "background", f"{name} overwrote a concurrent write")

    def test_take_directory_removal_runs_outside_the_project_lock(self) -> None:
        real_rmtree = shutil.rmtree
        cases = [
            ("delete_line", lambda: script_routes.delete_line("s1", "l1")),
            ("delete_scene", lambda: script_routes.delete_scene("s1")),
            ("clear_all_takes", script_routes.clear_all_takes),
        ]
        for name, handler in cases:
            with self.subTest(handler=name):
                takes = constants.MEDIA_ROOT / "takes"
                for line_id in ("l1", "l2", "l3"):
                    (takes / line_id).mkdir(parents=True, exist_ok=True)
                    (takes / line_id / "take.wav").write_bytes(_wav())
                states: list[bool] = []

                def observing_rmtree(path: Any, *args: Any, **kwargs: Any) -> None:
                    states.append(_lock_is_free_for_other_threads())
                    real_rmtree(path, *args, **kwargs)

                store = _Store()
                with (
                    patch("server.modules.project_repository.read_project", store.read_project),
                    patch("server.modules.project_repository.write_project", store.write_project),
                    patch("server.modules.export_service.require_tts_available", lambda **_: None),
                    patch("shutil.rmtree", observing_rmtree),
                ):
                    handler()
                self.assertTrue(states, f"{name} removed no media")
                self.assertTrue(all(states), f"{name} deleted media while holding the project lock")
                self.assertFalse((takes / "l1").exists(), f"{name} left the take directory behind")

    def test_global_cast_mutations_do_not_lose_a_concurrent_cast_write(self) -> None:
        def import_reference() -> None:
            character_routes.import_reference_wav(SimpleNamespace(
                audio_base64=base64.b64encode(_wav()).decode(), name="新規", profile=""))

        def apply_updates() -> None:
            snapshot = lambda character: {**character, "scope": "project"}  # noqa: E731
            with patch.object(cast_sync, "project_snapshot_from_global", side_effect=snapshot):
                cast_sync.apply_global_cast_updates(["a"])

        cases = [
            ("import_reference_wav", import_reference, lambda s: any(c.get("name") == "新規" for c in s.global_characters)),
            ("apply_global_cast_updates", apply_updates, lambda s: s.project["characters"][0]["name"] == "A2"),
        ]
        for name, handler, applied in cases:
            with self.subTest(handler=name):
                store = _Store(global_characters=[{"id": "a", "name": "A2"}])
                self._race(store, handler, _background_cast_writer)
                self.assertTrue(applied(store), f"{name} did not apply its own change")
                self.assertIn("background-cast", [c["id"] for c in store.global_characters])
                self.assertEqual(store.project["title"], "background", f"{name} overwrote a concurrent write")


def dictionary_then_project() -> None:
    """Take the locks in the order dictionary routes do."""
    with pronunciation_dictionary.DICTIONARY_LOCK, deps.PROJECT_ROOT_LOCK:
        time.sleep(0.001)


class HistoryLockOrderTests(unittest.TestCase):
    def _history_state(self) -> Any:
        snapshot = {"scope": "script", "projectRoot": "", "files": {}, "includeMedia": False, "mediaTargets": None}
        entry = {"before": snapshot, "after": dict(snapshot), "createdAt": 0.0, "generationGroupId": None}
        return (
            patch.object(history, "_HISTORY", {"script": [entry], "characters": [], "pronunciation": []}),
            patch.object(history, "_CURSOR", {"script": 1, "characters": 0, "pronunciation": 0}),
            patch.object(history, "_restored_media", return_value={}),
            patch.object(constants, "ACTIVE_PROJECT_PATH", None),
            patch("server.modules.derived_audio_preparation.reset_overlap_preparation"),
        )

    def test_apply_history_keeps_project_writers_out_between_check_and_restore(self) -> None:
        order: list[str] = []
        checked = threading.Event()

        def matches(_snapshot: dict[str, Any]) -> bool:
            checked.set()
            time.sleep(0.05)
            return True

        def restore(*_args: Any) -> None:
            time.sleep(_PAUSE_SECONDS)
            order.append("restore")

        def writer() -> None:
            self.assertTrue(checked.wait(2))
            with deps.PROJECT_ROOT_LOCK:
                order.append("writer")

        state = self._history_state()
        with state[0], state[1], state[2], state[3], state[4], \
                patch.object(history, "_live_metadata_matches", side_effect=matches), \
                patch.object(history, "_restore", side_effect=restore):
            thread = threading.Thread(target=writer)
            thread.start()
            history.apply_history("script", "undo")
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(order, ["restore", "writer"])

    def test_apply_history_keeps_dictionary_writers_out_between_check_and_restore(self) -> None:
        order: list[str] = []
        checked = threading.Event()

        def matches(_snapshot: dict[str, Any]) -> bool:
            checked.set()
            time.sleep(0.05)
            return True

        def restore(*_args: Any) -> None:
            time.sleep(_PAUSE_SECONDS)
            order.append("restore")

        @pronunciation_dictionary.dictionary_transaction
        def dictionary_writer() -> None:
            order.append("dictionary")

        def writer() -> None:
            self.assertTrue(checked.wait(2))
            dictionary_writer()

        state = self._history_state()
        with state[0], state[1], state[2], state[3], state[4], \
                patch.object(history, "_live_metadata_matches", side_effect=matches), \
                patch.object(history, "_restore", side_effect=restore):
            thread = threading.Thread(target=writer)
            thread.start()
            history.apply_history("script", "undo")
            thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(order, ["restore", "dictionary"])

    def test_apply_history_and_locked_handlers_do_not_deadlock(self) -> None:
        state = self._history_state()
        with tempfile.TemporaryDirectory() as directory, state[2], state[3], state[4], \
                patch.object(constants, "MEDIA_ROOT", Path(directory)), \
                patch.object(history, "_live_metadata_matches", return_value=True), \
                patch.object(history, "_restore", side_effect=lambda *_: time.sleep(0.001)), \
                patch.object(history, "_snapshot", side_effect=lambda scope, *_: {"scope": scope, "files": {}}):
            store = _Store()
            with patch("server.modules.project_repository.read_project", store.read_project), \
                    patch("server.modules.project_repository.write_project", store.write_project), \
                    patch("server.modules.project_repository.read_global_characters", store.read_global_characters), \
                    patch("server.modules.project_repository.write_global_characters", store.write_global_characters):
                for _ in range(20):
                    store.project = _project()
                    barrier = threading.Barrier(4)
                    with patch.object(history, "_HISTORY", {"script": [{"before": {"files": {}, "mediaTargets": None},
                                                                         "after": {"files": {}}}], "characters": [],
                                                              "pronunciation": []}), \
                            patch.object(history, "_CURSOR", {"script": 1, "characters": 0, "pronunciation": 0}):
                        workers = [
                            lambda: history.apply_history("script", "undo"),
                            lambda: script_routes.delete_line("s1", "l1"),
                            lambda: history.release_history_capture(history.capture_history_before("script")),
                            dictionary_then_project,
                        ]
                        threads = [threading.Thread(target=lambda work=work: (barrier.wait(), work())) for work in workers]
                        for thread in threads:
                            thread.start()
                        for thread in threads:
                            thread.join(timeout=5)
                        self.assertFalse(any(thread.is_alive() for thread in threads), "lock order deadlocked")


if __name__ == "__main__":
    unittest.main()
