"""Fetch missing notices from version-specific registry archives, without executing package code."""
import hashlib
import io
import json
import tarfile
import tomllib
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from email.parser import Parser
from pathlib import Path

from license_sources import LICENSE_NAME

ROOT = Path(__file__).resolve().parents[2]


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        data = response.read(100_000_001)
    if len(data) > 100_000_000:
        raise ValueError("Archive exceeds inspection limit")
    return data


def archive_files(data):
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return [(info.filename, archive.read(info)) for info in archive.infolist() if relevant(info.filename) and info.file_size < 4_000_000]
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
        return [(info.name, archive.extractfile(info).read()) for info in archive.getmembers() if info.isfile() and relevant(info.name) and info.size < 4_000_000]


def relevant(name):
    path = Path(name)
    return bool(LICENSE_NAME.match(path.name)) or "licenses" in path.parts or path.name in {"package.json", "Cargo.toml", "METADATA", "PKG-INFO"}


def source(entry):
    ecosystem, name, version = entry["ecosystem"], entry["name"], entry["version"]
    if ecosystem == "cargo":
        locks = [tomllib.loads((ROOT / file).read_text()) for file in ["src-tauri/Cargo.lock", "native/scena-native/Cargo.lock"]]
        package = next(package for lock in locks for package in lock["package"] if package["name"] == name and package["version"] == version)
        return f"https://static.crates.io/crates/{name}/{name}-{version}.crate", package["checksum"], "UNKNOWN"
    if ecosystem == "npm":
        metadata = json.loads(fetch(f"https://registry.npmjs.org/{name}/{version}"))
        return metadata["dist"]["tarball"], "", metadata.get("license", "UNKNOWN")
    metadata = json.loads(fetch(f"https://pypi.org/pypi/{name}/{version}/json"))
    candidates = metadata["urls"]
    item = next((item for item in candidates if item["filename"].endswith(".whl")), candidates[0])
    info = metadata["info"]
    return item["url"], item["digests"]["sha256"], info.get("license_expression") or info.get("license") or "UNKNOWN"


def collect(entry):
    try:
        url, expected, license_id = source(entry)
        data = fetch(url)
        digest = hashlib.sha256(data).hexdigest()
        if expected and digest != expected:
            raise ValueError("Archive checksum mismatch")
        files = archive_files(data)
        if entry["ecosystem"] == "cargo":
            metadata = next(content for name, content in files if name.count("/") == 1 and name.endswith("/Cargo.toml"))
            license_id = tomllib.loads(metadata.decode())["package"].get("license", "UNKNOWN")
        if len(str(license_id)) > 200:
            license_id = "SEE LICENSE TEXT"
        result = {"id": entry["id"], "license": license_id, "archiveUrl": url, "archiveSha256": digest, "files": []}
        directory = ROOT / "licenses/sources" / hashlib.sha256(entry["id"].encode()).hexdigest()[:20]
        for name, content in files:
            if not LICENSE_NAME.match(Path(name).name) and "licenses" not in Path(name).parts:
                if Path(name).name in {"METADATA", "PKG-INFO"} and license_id == "UNKNOWN":
                    fields = Parser().parsestr(content.decode())
                    candidates = [value.rsplit(" :: ", 1)[-1] for value in fields.get_all("Classifier", []) if value.startswith("License :: OSI Approved ::")]
                    if candidates:
                        result["license"] = " / ".join(candidates)
                continue
            text = content.decode("utf-8")
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / (hashlib.sha256(name.encode()).hexdigest()[:12] + ".txt")
            target.write_text(text)
            result["files"].append(str(target.relative_to(ROOT)))
        result["files"].sort()
        return result, None
    except Exception as error:
        return None, {"id": entry["id"], "error": type(error).__name__}


def main():
    inventory = json.loads((ROOT / "licenses/inventory.json").read_text())
    pending = [entry for entry in inventory["entries"] if entry["status"] == "needs-review" and entry["ecosystem"] in {"cargo", "npm", "pypi"}]
    path = ROOT / "release-license-supplements.json"
    supplements = json.loads(path.read_text())
    entries = {entry["id"]: entry for entry in supplements["packages"]}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result, error in pool.map(collect, pending):
            if error:
                print(json.dumps(error), flush=True)
            else:
                entries[result["id"]] = result
    supplements["packages"] = sorted(entries.values(), key=lambda entry: entry["id"])
    path.write_text(json.dumps(supplements, ensure_ascii=False, indent=2) + "\n")
    print(f"Inspected {len(pending)} version-specific archives")


if __name__ == "__main__":
    main()
