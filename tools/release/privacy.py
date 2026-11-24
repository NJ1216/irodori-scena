"""Public snapshot audit. Findings contain locations and categories, never values."""
import hashlib
import gzip
import io
import zlib
import re
import struct
from pathlib import Path

FORBIDDEN = {".git", ".env", ".agents", ".codex", ".serena", ".basic-memory", "decisions", "artifacts", "scena-data", "userproject", "node_modules", ".venv", ".uv-cache", "target", "build", "dist", "coverage", "test-results", "playwright-report"}
RULES = {
    "private-key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "aws-key": re.compile(rb"AKIA[A-Z0-9]{16}"),
    "credential-assignment": re.compile(rb'(?i)(?:api[_-]?key|access[_-]?token|password)\s*[=:]\s*[\"\'][A-Za-z0-9_+/=-]{16,}[\"\']'),
    "access-token": re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-|svcacct-)?[A-Za-z0-9_]{20,})"),
    "local-home": re.compile(rb"(?:/Users/|/home/|[A-Z]:\\Users\\)(?!example(?:[/\\]|\b)|test(?:[/\\]|\b)|user(?:[/\\]|\b))[^\s/\\\"']+"),
    "memory-content": re.compile(rb"(?:^permalink:|memory://|^type: note\s*$)", re.M),
    "email-review": re.compile(rb"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    # Tailnet machine names and self-hosted Gitea remotes identify the owner's private network.
    "private-host": re.compile(rb"(?i)[a-z0-9-]+\.tail[0-9a-f]+\.ts\.net|https?://[a-z0-9.-]+:3000/"),
}
PNG_TEXT = {b"tEXt", b"iTXt", b"zTXt", b"eXIf"}


def image_metadata(name, data):
    """True when an image carries text, EXIF or XMP metadata (author, device, dates, paths)."""
    lower = name.lower()
    if lower.endswith(".png") and data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        while offset + 8 <= len(data):
            length, kind = struct.unpack(">I4s", data[offset:offset + 8])
            if kind in PNG_TEXT:
                return True
            offset += 12 + length
        return False
    if lower.endswith(".webp") and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        offset = 12
        while offset + 8 <= len(data):
            kind, length = struct.unpack("<4sI", data[offset:offset + 8])
            if kind in (b"EXIF", b"XMP "):
                return True
            offset += 8 + length + (length % 2)
        return False
    if lower.endswith((".jpg", ".jpeg")) and data[:2] == b"\xff\xd8":
        offset = 2
        while offset + 4 <= len(data) and data[offset] == 0xFF:
            marker = data[offset + 1]
            if marker == 0xDA:
                return False
            (length,) = struct.unpack(">H", data[offset + 2:offset + 4])
            if marker == 0xE1:
                return True
            offset += 2 + length
    return False


def safe_name(name):
    parts = Path(name).parts
    return bool(parts) and not Path(name).is_absolute() and ".." not in parts and not FORBIDDEN.intersection(parts) and parts[-1] != "AGENTS.md" and (parts[0] != "docs" or parts[:2] == ("docs", "public"))


def public_bytes(root, name):
    data = (root / name).read_bytes()
    if name.endswith(".md") and data.startswith(b"---\n"):
        end = data.find(b"\n---\n", 4)
        if end >= 0 and b"type: note" in data[:end]:
            data = data[end + 5:].lstrip(b"\n")
    return data.rstrip(b"\n") + b"\n" if name.endswith(".md") else data


def audit_file(root, name, exceptions=None, private_terms=()):
    findings = []
    relative = Path(name)
    if not safe_name(name) or any((root / Path(*relative.parts[:i])).is_symlink() for i in range(1, len(relative.parts) + 1)):
        return [{"file": name, "kind": "forbidden-path"}]
    data = public_bytes(root, name)
    digest = hashlib.sha256(data).hexdigest()
    if name.endswith(".json.gz"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                data = compressed.read(10_000_001)
            if len(data) > 10_000_000:
                return [{"file": name, "kind": "compressed-content-limit"}]
        except (OSError, EOFError, zlib.error):
            return [{"file": name, "kind": "invalid-compressed-content"}]
    allowed = (exceptions or {}).get(name, {})
    for kind, pattern in RULES.items():
        if pattern.search(data) and not (allowed.get("sha256") == digest and kind in allowed.get("rules", []) and allowed.get("reason")):
            findings.append({"file": name, "kind": kind})
    if image_metadata(name, data) and not ("image-metadata" in allowed.get("rules", []) and allowed.get("sha256") == digest and allowed.get("reason")):
        findings.append({"file": name, "kind": "image-metadata"})
    if any(term.encode().lower() in data.lower() for term in private_terms if term):
        findings.append({"file": name, "kind": "private-term"})
    return findings
