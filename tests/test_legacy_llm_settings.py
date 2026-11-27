from __future__ import annotations

import scena_test_isolation  # noqa: F401
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server.app  # noqa: F401
from server.modules import connection_settings, constants, workspace


class LegacyLlmSettingsTests(unittest.TestCase):
    def test_discards_legacy_llm_fields_but_preserves_engine_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings_file = Path(temporary) / "connection.json"
            settings_file.write_text(json.dumps({"provider": "openai", "baseUrl": "https://example.invalid/v1",
                                                 "model": "old", "apiKeyEnabled": True,
                                                 "engineDir": "/engines/Irodori-TTS"}))
            with (
                patch.object(constants, "CONNECTION_SETTINGS_FILE", settings_file),
                patch.object(connection_settings.keyring, "delete_password") as delete_secret,
            ):
                workspace.discard_legacy_llm_settings()
            self.assertEqual(json.loads(settings_file.read_text()), {"engineDir": "/engines/Irodori-TTS"})
            delete_secret.assert_called_once()


if __name__ == "__main__":
    unittest.main()
