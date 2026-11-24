from __future__ import annotations

import unittest
from server.app import draft_context_inventory


class DraftOptionalContextTests(unittest.TestCase):
    character = {
        "id": "private-cast-id",
        "name": "莉里",
        "profileDetails": {"hobbies": "天体観測"},
    }

    def test_inventory_includes_bounded_values_without_persistent_ids(self) -> None:
        inventory = draft_context_inventory([self.character], {"private-cast-id": "A"})
        self.assertEqual(inventory[0]["available_optional_fields"], [
            {"field": "hobbies", "label": "趣味", "value": "天体観測"}
        ])
        self.assertNotIn("private-cast-id", str(inventory))

if __name__ == "__main__":
    unittest.main()
