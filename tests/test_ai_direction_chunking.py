from __future__ import annotations

import unittest
from server.modules.direction_context import DIRECTION_CHUNK_SIZE, direction_chunk_size


class AiDirectionChunkingTests(unittest.TestCase):
    def test_selector_uses_only_validated_bounded_sizes(self) -> None:
        for size in (10, 20, 30, 50, 100):
            with self.subTest(size=size):
                self.assertEqual(direction_chunk_size({"directionChunkSize": size}), size)

    def test_context_alone_does_not_bypass_the_capability_profile(self) -> None:
        for context in (4096, 8192, 16384, 32768, 65536):
            with self.subTest(context=context):
                self.assertEqual(direction_chunk_size({"effectiveContext": context}), 30)

    def test_missing_or_invalid_capability_fails_closed(self) -> None:
        self.assertEqual(direction_chunk_size(None, experimental=True), DIRECTION_CHUNK_SIZE)
        self.assertEqual(direction_chunk_size({"effectiveContext": True}, experimental=True), DIRECTION_CHUNK_SIZE)
        self.assertEqual(direction_chunk_size({"effectiveContext": "32768"}, experimental=True), DIRECTION_CHUNK_SIZE)

if __name__ == "__main__":
    unittest.main()
