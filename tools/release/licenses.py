"""Generate offline acknowledgments from exact package sources and reviewed supplements."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from license_sources import javascript, python_packages, rust
from privacy import public_bytes
from runtime_inventory import runtime_entries

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ["pnpm-lock.yaml", "uv.lock", "src-tauri/Cargo.lock", "native/scena-native/Cargo.lock", "tools/omlx-runtime-requirements.txt", "release-license-supplements.json", "server/modules/tts_catalog.py", "LICENSE"]


def generate():
    texts, entries = {}, []
    supplements = json.loads((ROOT / "release-license-supplements.json").read_text())
    overrides = {entry["id"]: entry for entry in supplements["packages"]}
    known = {}
    for entry, files in [*javascript(ROOT), *rust(ROOT), *python_packages(ROOT), *runtime_entries(ROOT)]:
        identity = entry.get("id") or f"{entry['ecosystem']}:{entry['name']}@{entry['version']}"
        entry["id"] = identity
        key = (entry["ecosystem"], entry["name"], entry["version"])
        if not files and key in known:
            prior, files = known[key]
            entry["license"] = prior["license"]
        if identity in overrides:
            override = overrides.pop(identity)
            entry.update({key: value for key, value in override.items() if key != "files"})
            if "files" in override:
                files = [(name, (ROOT / name).read_text()) for name in override["files"]]
        known[key] = (entry, files)
        entry["texts"] = []
        for name, content in files:
            digest = hashlib.sha256(content.encode()).hexdigest()
            texts[digest] = content
            entry["texts"].append({"name": name, "sha256": digest})
        entry["status"] = "collected" if entry["texts"] and entry["license"] != "UNKNOWN" else "needs-review"
        entries.append(entry)
    for entry in overrides.values():
        if entry.get("ecosystem") != "tool":
            continue
        entry = dict(entry)
        entry["texts"] = []
        for name in entry.pop("files", []):
            content = (ROOT / name).read_text()
            digest = hashlib.sha256(content.encode()).hexdigest()
            texts[digest] = content
            entry["texts"].append({"name": name, "sha256": digest})
        entry.setdefault("status", "collected" if entry["texts"] else "needs-review")
        entries.append(entry)
    return {"schemaVersion": 1, "applicationLicense": (ROOT / "LICENSE").read_text(), "inputs": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}, "entries": sorted(entries, key=lambda entry: entry["id"]), "texts": dict(sorted(texts.items()))}


def markdown(data):
    lines = ["# Third-party notices", "", "Generated with `pnpm release:licenses`. Application licensing does not replace these terms.", "", "Build dependencies and runtime downloads are identified separately. Collected text is not a legal compatibility approval.", ""]
    for entry in data["entries"]:
        lines.extend([f"## {entry['id']}", "", f"{entry['scope']} · {entry['license']} · {entry['status']}", "", entry["source"], ""])
        for reference in entry["texts"]:
            lines.extend([f"### {reference['name']}", "", data["texts"][reference["sha256"]], ""])
    return "\n".join(lines)


def compressed_display(data):
    fields = ("id", "name", "version", "license", "source", "scope", "status", "texts")
    display = {"applicationLicense": data["applicationLicense"], "entries": [{key: entry[key] for key in fields} for entry in data["entries"]], "texts": data["texts"]}
    return gzip.compress(json.dumps(display, ensure_ascii=False, separators=(",", ":")).encode(), compresslevel=9, mtime=0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data = generate()
    outputs = {"licenses/inventory.json": json.dumps(data, ensure_ascii=False, indent=2) + "\n", "THIRD_PARTY_NOTICES.md": markdown(data)}
    for name, content in outputs.items():
        if args.check:
            if public_bytes(ROOT, name).decode().rstrip("\n") != content.rstrip("\n"):
                raise SystemExit(f"Generated notices differ: {name}")
        else:
            (ROOT / name).write_text(content)
    compressed_path = ROOT / "public/third-party-licenses.json.gz"
    compressed = compressed_display(data)
    if args.check:
        if not compressed_path.exists() or compressed_path.read_bytes() != compressed:
            raise SystemExit("Compressed license resource differs; run pnpm release:licenses")
    else:
        compressed_path.write_bytes(compressed)
    pending = [entry["id"] for entry in data["entries"] if entry["status"] != "collected"]
    print(json.dumps({"packages": len(data["entries"]), "needsReview": pending}, indent=2))


if __name__ == "__main__":
    main()
