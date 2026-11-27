from __future__ import annotations

import scena_test_isolation  # noqa: F401
import asyncio
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import server.app  # noqa: F401
from fastapi.testclient import TestClient
from server.app import app
from starlette.requests import Request
from starlette.responses import Response
from server.modules import constants, history


class HistoryMediaTargetTests(unittest.TestCase):
    def test_history_middleware_keeps_the_batch_delete_body_available_to_the_route(self) -> None:
        payload = {"line_ids": ["line-1"]}
        body = json.dumps(payload).encode()

        async def exercise():
            sent = False

            async def receive():
                nonlocal sent
                if sent:
                    return {"type": "http.request", "body": b"", "more_body": False}
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}

            request = Request(
                {"type": "http", "method": "POST", "path": "/api/lines/batch-delete", "headers": []},
                receive,
            )

            async def call_next(inner):
                self.assertEqual(await inner.json(), payload)
                return Response(status_code=200)

            with (
                patch.object(history, "capture_history_before", return_value={"files": {}}),
                patch.object(history, "commit_history"),
            ):
                await history.history_middleware(request, call_next)

        asyncio.run(exercise())

    def test_batch_delete_body_reaches_the_registered_api_route(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            media = root / "media"
            project_file = root / "project.json"
            project_file.write_text('{"id":"project"}', encoding="utf-8")
            take = media / "takes/line-1/take.wav"
            take.parent.mkdir(parents=True)
            take.write_bytes(b"take")
            project = {"scenes": [{"id": "scene-1", "lines": [{"id": "line-1", "takes": []}]}]}
            with (
                patch.object(constants, "DATA_ROOT", root / "data"),
                patch.object(constants, "ACTIVE_PROJECT_ROOT", root),
                patch.object(constants, "PROJECT_FILE", project_file),
                patch.object(constants, "MEDIA_ROOT", media),
                patch("server.modules.project_repository.read_project", return_value=project),
                patch("server.modules.project_repository.write_project", side_effect=lambda value: value),
                patch("server.modules.dialogue_cues.normalize_scene_cues"),
            ):
                history.begin_history_session()
                response = TestClient(app).post("/api/lines/batch-delete", json={"line_ids": ["line-1"]})
                history.end_history_session()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["scenes"][0]["lines"], [])



async def _async_value(value):
    return value



if __name__ == "__main__":
    unittest.main()
