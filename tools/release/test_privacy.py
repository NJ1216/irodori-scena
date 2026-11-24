import hashlib
import gzip
import struct
import zlib
import tempfile
import unittest
from pathlib import Path

from privacy import audit_file, safe_name, public_bytes


def png(*chunks):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    header = chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0))
    return b"\x89PNG\r\n\x1a\n" + header + b"".join(chunk(kind, body) for kind, body in chunks) + chunk(b"IDAT", zlib.compress(b"\0\0")) + chunk(b"IEND", b"")


def webp(*chunks):
    body = b"WEBP" + b"".join(kind + struct.pack("<I", len(data)) + data + (b"\0" if len(data) % 2 else b"") for kind, data in chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def jpeg(*segments):
    return b"\xff\xd8" + b"".join(b"\xff" + bytes([marker]) + struct.pack(">H", len(data) + 2) + data for marker, data in segments) + b"\xff\xda\x00\x02\xff\xd9"


class PrivacyTest(unittest.TestCase):
    def test_private_host_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "example.md"
            for text in ["see http://build-box" + ".tail" + "0a1b2c" + ".ts.net/x", "git remote http://host.example:" + "3000/owner/repo.git"]:
                file.write_text(text)
                self.assertEqual(audit_file(root, file.name), [{"file": file.name, "kind": "private-host"}], text)
            file.write_text("Tauri listens on http://127.0.0.1:5173/ and https://github.com/owner/repo")
            self.assertEqual(audit_file(root, file.name), [])

    def test_image_metadata_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {
                "text.png": png((b"tEXt", b"Author\0someone")),
                "exif.png": png((b"eXIf", b"MM\0*")),
                "exif.webp": webp((b"VP8L", b"\x2f\0\0\0"), (b"EXIF", b"MM\0*")),
                "xmp.webp": webp((b"VP8L", b"\x2f\0\0\0"), (b"XMP ", b"<x/>")),
                "exif.jpg": jpeg((0xE1, b"Exif\0\0MM")),
            }
            for name, data in cases.items():
                (root / name).write_bytes(data)
                self.assertEqual(audit_file(root, name), [{"file": name, "kind": "image-metadata"}], name)
            clean = {"clean.png": png((b"sRGB", b"\0")), "clean.webp": webp((b"VP8L", b"\x2f\0\0\0")), "clean.jpg": jpeg((0xE0, b"JFIF\0\1\1"))}
            for name, data in clean.items():
                (root / name).write_bytes(data)
                self.assertEqual(audit_file(root, name), [], name)

    def test_compressed_assets_are_audited_without_changing_exported_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            name = "notices.json.gz"
            content = gzip.compress(b'{"text":"memory://internal-note"}', mtime=0)
            (root / name).write_bytes(content)
            self.assertEqual(public_bytes(root, name), content)
            self.assertEqual(audit_file(root, name), [{"file": name, "kind": "memory-content"}])
            (root / name).write_bytes(content[:12])
            self.assertEqual(audit_file(root, name)[0]["kind"], "invalid-compressed-content")
            (root / name).write_bytes(gzip.compress(b"x" * 10_000_001, mtime=0))
            self.assertEqual(audit_file(root, name)[0]["kind"], "compressed-content-limit")

    def test_forbidden_paths_and_traversal(self):
        for path in [".git/config", "docs/notes/example.md", "decisions/example.md", ".codex/settings.json", "AGENTS.md", "../outside", "/absolute", "src/../secret"]:
            self.assertFalse(safe_name(path), path)
        self.assertTrue(safe_name("docs/public/build.md"))

    def test_masked_findings_and_bound_exceptions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "example.txt"
            file.write_text("contact@example.com")
            self.assertEqual(audit_file(root, file.name), [{"file": file.name, "kind": "email-review"}])
            exceptions = {file.name: {"sha256": hashlib.sha256(file.read_bytes()).hexdigest(), "rules": ["email-review"], "reason": "Synthetic fixture"}}
            self.assertEqual(audit_file(root, file.name, exceptions), [])
            file.write_text("changed@example.com")
            self.assertTrue(audit_file(root, file.name, exceptions))

    def test_home_and_memory_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "example.txt"
            file.write_text("/Users/" + "private-person/project")
            self.assertEqual(audit_file(root, file.name)[0]["kind"], "local-home")
            file.write_text("/Users/example/project")
            self.assertEqual(audit_file(root, file.name), [])
            file.write_text("permalink:" + " internal-note")
            self.assertEqual(audit_file(root, file.name)[0]["kind"], "memory-content")
            (root / "link").symlink_to(file)
            self.assertEqual(audit_file(root, "link")[0]["kind"], "forbidden-path")


if __name__ == "__main__":
    unittest.main()
