import hashlib
import gzip
import json
import unittest
from pathlib import Path

from licenses import markdown, compressed_display
from license_sources import javascript
from runtime_inventory import runtime_entries

ROOT = Path(__file__).resolve().parents[2]


class LicenseTest(unittest.TestCase):
    def test_runtime_inventory_includes_pinned_optional_tts_models(self):
        entries = {entry["id"]: entry for entry, _ in runtime_entries(ROOT)}
        mf_id = "download:Aratako/Irodori-TTS-v4.1-Small-MF@ccc78f5d480b6e51b69b2d5042a14c4da04fea6e"
        anime_id = "download:phasefield-audio/Irodori-TTS-v4.1-Anime@6b259f5baa5e236b3d14cbd1f8555ca87d92b530"
        self.assertIn("download:Aratako/Irodori-TTS-v4-Large@2e0c55428ce97268a507f1feeb2478f8d9148e8b", entries)
        self.assertIn("download:Aratako/Irodori-TTS-v4-Large-Quantized@bdef9592db4426bd1c99ccdf0cfc3a213223fb61", entries)
        self.assertIn(mf_id, entries)
        self.assertIn(anime_id, entries)
        inventory = {entry["id"]: entry for entry in json.loads((ROOT / "licenses/inventory.json").read_text())["entries"]}
        self.assertEqual(inventory[mf_id]["license"], "mit")
        self.assertEqual(inventory[anime_id]["license"], "mit")
        self.assertEqual(inventory[anime_id]["status"], "collected")
        self.assertFalse(any("Irodori-TTS-500M-v2" in identity for identity in entries))
        self.assertFalse(any("Irodori-TTS-500M-v2" in identity for identity in inventory))

    def test_every_locked_javascript_identity_is_unique(self):
        packages = list(javascript(ROOT))
        identities = [(entry["name"], entry["version"]) for entry, _ in packages]
        self.assertEqual(len(identities), len(set(identities)))
        self.assertIn(("react", "19.2.8"), identities)

    def test_compressed_resource_preserves_every_notice_and_is_deterministic(self):
        data = json.loads((ROOT / "licenses/inventory.json").read_text())
        compressed = compressed_display(data)
        decoded = json.loads(gzip.decompress(compressed))
        self.assertEqual(decoded["texts"], data["texts"])
        self.assertEqual(decoded["applicationLicense"], data["applicationLicense"])
        self.assertEqual([entry["id"] for entry in decoded["entries"]], [entry["id"] for entry in data["entries"]])
        self.assertEqual(compressed, compressed_display(data))
        self.assertLess(len(compressed), len(json.dumps(data).encode()) // 4)

    def test_markdown_contains_exact_license_text(self):
        text = "Copyright Example\nPermission is granted.\n"
        digest = hashlib.sha256(text.encode()).hexdigest()
        data = {"entries": [{"id": "example", "scope": "build", "license": "MIT", "status": "collected", "source": "https://example.com", "texts": [{"name": "LICENSE", "sha256": digest}]}], "texts": {digest: text}}
        self.assertIn(text, markdown(data))
        self.assertEqual(markdown(data), markdown(json.loads(json.dumps(data))))


if __name__ == "__main__":
    unittest.main()
