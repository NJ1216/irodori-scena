"""Read exact installed packages matching lockfile identities; do not scan the whole environment."""
import importlib.metadata
import json
import re
import tomllib
from pathlib import Path

LICENSE_NAME = re.compile(r"^(?:licen[cs]e|copying|copyright|notice|authors)(?:[._-].*)?$", re.I)


def license_files(directory):
    files = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if "node_modules" in relative.parts or len(relative.parts) > 4:
            continue
        if path.is_file() and (LICENSE_NAME.match(path.name) or any(p.lower() in {"licenses", "license"} for p in relative.parts[:-1])):
            try:
                files.append((str(relative), path.read_text(encoding="utf-8")))
            except UnicodeDecodeError:
                continue
    return files


def javascript(root):
    # Only top-level package keys inside the lockfile's packages section are identities.
    section = (root / "pnpm-lock.yaml").read_text().split("\npackages:\n", 1)[1].split("\nsnapshots:", 1)[0]
    installed = {}
    for file in sorted((root / "node_modules/.pnpm").glob("*/node_modules/*/package.json")) + sorted((root / "node_modules/.pnpm").glob("*/node_modules/@*/*/package.json")):
        metadata = json.loads(file.read_text())
        installed.setdefault((metadata.get("name"), metadata.get("version")), (file.parent, metadata))
    for line in section.splitlines():
        match = re.match(r"^  [\"']?(\S+?)[\"']?:$", line)
        if not match:
            continue
        name, version = match[1].rsplit("@", 1)
        directory, metadata = installed.get((name, version), (None, {}))
        yield {"ecosystem": "npm", "name": name, "version": version, "license": metadata.get("license", "UNKNOWN"), "source": f"https://www.npmjs.com/package/{name}/v/{version}", "scope": "build-and-application"}, license_files(directory) if directory else []


def rust(root):
    seen = set()
    registry = Path.home() / ".cargo/registry/src"
    for lockfile in ["src-tauri/Cargo.lock", "native/scena-native/Cargo.lock"]:
        for package in tomllib.loads((root / lockfile).read_text())["package"]:
            name, version = package["name"], package["version"]
            if not package.get("source") or (name, version) in seen:
                continue
            seen.add((name, version))
            directory = next(registry.glob(f"*/{name}-{version}"), None)
            metadata = tomllib.loads((directory / "Cargo.toml").read_text())["package"] if directory else {}
            files = license_files(directory) if directory else []
            license_file = metadata.get("license-file")
            if directory and license_file and (directory / license_file).is_file() and license_file not in dict(files):
                files.append((license_file, (directory / license_file).read_text()))
            yield {"ecosystem": "cargo", "name": name, "version": version, "license": metadata.get("license", "UNKNOWN"), "source": f"https://crates.io/crates/{name}/{version}", "scope": "build-and-application"}, files


def python_packages(root):
    for package in tomllib.loads((root / "uv.lock").read_text())["package"]:
        name, version = package["name"], package["version"]
        if name == "irodori-scena-local-api":
            continue
        files, license_id = [], "UNKNOWN"
        try:
            distribution = importlib.metadata.distribution(name)
            if distribution.version == version:
                license_id = distribution.metadata.get("License-Expression") or distribution.metadata.get("License") or "UNKNOWN"
                if len(license_id) > 200:
                    license_id = "SEE LICENSE TEXT"
                files = distribution_licenses(distribution)
        except importlib.metadata.PackageNotFoundError:
            pass
        yield {"ecosystem": "pypi", "name": name, "version": version, "license": license_id, "source": f"https://pypi.org/project/{name}/{version}/", "scope": "build-and-api"}, files


def distribution_licenses(distribution):
    files = []
    for file in distribution.files or []:
        if file.suffix not in {".py", ".pyc", ".so"} and (LICENSE_NAME.match(file.name) or "licenses" in file.parts):
            path = Path(distribution.locate_file(file))
            if path.is_file():
                try:
                    files.append((str(file), path.read_text(encoding="utf-8")))
                except UnicodeDecodeError:
                    continue
    return sorted(files)
