from __future__ import annotations

import unittest

from server.modules.project_repository import normalize_project_media_urls


class ProjectMediaUrlTests(unittest.TestCase):
    def test_normalizes_desktop_api_urls_before_project_persistence(self) -> None:
        project = {
            "scenes": [{
                "lines": [{
                    "takes": [{
                        "audioUrl": "http://127.0.0.1:49152/media/takes/line-1/take-1.wav",
                    }],
                }],
            }],
            "characters": [{
                "referenceAudioUrl": "http://localhost:49152/media/characters/cast-1/reference.wav",
            }],
        }

        normalized = normalize_project_media_urls(project)

        self.assertEqual(
            normalized["scenes"][0]["lines"][0]["takes"][0]["audioUrl"],
            "/media/takes/line-1/take-1.wav",
        )
        self.assertEqual(
            normalized["characters"][0]["referenceAudioUrl"],
            "/media/characters/cast-1/reference.wav",
        )

    def test_does_not_rewrite_external_urls(self) -> None:
        value = {"audioUrl": "https://example.com/media/take.wav"}

        self.assertEqual(normalize_project_media_urls(value), value)


if __name__ == "__main__":
    unittest.main()
