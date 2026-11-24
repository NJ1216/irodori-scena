#!/usr/bin/env python3
"""Create a deterministic, minimal SCENA Rhubarb add-on archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inputs(root: Path, executable_name: str) -> list[Path]:
    required = [root / executable_name, root / "LICENSE.md"]
    missing = [str(path) for path in required if not path.is_file()]
    sphinx = root / "res" / "sphinx"
    if not sphinx.is_dir():
        missing.append(str(sphinx))
    if missing:
        raise ValueError("必要なRhubarbファイルがありません: " + ", ".join(missing))
    files = required + [path for path in sphinx.rglob("*") if path.is_file()]
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def build(root: Path, output: Path, platform_key: str, commit: str,
          japanese_addon: Path | None = None) -> dict[str, object]:
    executable_name = "rhubarb.exe" if platform_key == "windows-x64" else "rhubarb"
    source_files = inputs(root, executable_name)
    with tempfile.TemporaryDirectory(prefix="scena-rhubarb-package-") as temporary:
        package_root = Path(temporary) / "rhubarb"
        for source in source_files:
            destination = package_root / source.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        addon_identity = None
        executable_members = {"rhubarb/" + executable_name}
        if japanese_addon is not None:
            from server.modules.japanese_lipsync_addon import verify_assets
            manifest = japanese_addon / 'manifest.json'
            data = json.loads(manifest.read_text(encoding='utf-8'))
            verify_assets(japanese_addon, data['files'])
            if data.get('executable'):
                executable_members.add('rhubarb/japanese-lipsync/' + data['executable'])
            destination = package_root / 'japanese-lipsync'
            destination.mkdir()
            for name in [*data['files'], 'manifest.json']:
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(japanese_addon / name, target)
            addon_identity = {'manifestSha256': sha256(manifest), 'analysisVersion': data['analysisVersion'],
                              'license': 'Apache-2.0', 'publicationReview': data['publicationReview'],
                              'publicationReady': data.get('publicationReady', False)}
        info = {
            "schemaVersion": 1,
            "upstreamVersion": "1.14.0",
            "upstreamCommit": commit,
            "platform": platform_key,
            "contents": "minimal phonetic recognizer runtime",
            "license": "MIT",
            "signing": "ad-hoc" if platform_key == "darwin-arm64" else "unmodified executable from upstream Windows release",
        }
        (package_root / "BUILD-INFO.json").write_text(json.dumps(info, indent=2) + "\n")
        members = sorted((path for path in package_root.rglob("*") if path.is_file()), key=lambda path: path.relative_to(Path(temporary)).as_posix())
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in members:
                name = path.relative_to(Path(temporary)).as_posix()
                item = zipfile.ZipInfo(name, FIXED_TIME)
                item.external_attr = (0o755 if name in executable_members else 0o644) << 16
                archive.writestr(item, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    files = [item.filename for item in zipfile.ZipFile(output).infolist() if not item.is_dir()]
    executable = next(item for item in files if item.endswith("/" + executable_name))
    with zipfile.ZipFile(output) as archive:
        executable_hash = hashlib.sha256(archive.read(executable)).hexdigest()
    result = {"available": True, "archiveName": output.name, "archiveBytes": output.stat().st_size, "archiveSha256": sha256(output), "executable": executable, "executableSha256": executable_hash, "files": files}
    if addon_identity:
        result['japaneseAddon'] = addon_identity
        result['publicationReady'] = addon_identity['publicationReady']
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True, help="Prepared upstream distribution root")
    parser.add_argument("--platform", choices=("darwin-arm64", "windows-x64"), required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument('--japanese-addon', type=Path, help='Verified local review worker directory')
    args = parser.parse_args()
    result = build(args.root.resolve(), args.output.resolve(), args.platform, args.commit, args.japanese_addon)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
