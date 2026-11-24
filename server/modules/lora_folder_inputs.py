"""WAV-led recursive folder staging with bounded, non-following source reads."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import unicodedata
import uuid

from fastapi import HTTPException

from server.modules.lora_inputs import MAX_FILE_BYTES, MAX_TOTAL_BYTES, _row, input_audio_url
from server.modules.lora_storage import digest, owned_path, write_json

MAX_FOLDER_ENTRIES = 10000
MAX_FOLDER_FILES = 500


def scan_folder(source: Path) -> list[Path]:
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise HTTPException(422, "通常のフォルダを選択してください。シンボリックリンクは使えません。")
    files = []
    entries = 0
    def walk_error(error):
        raise HTTPException(422, "フォルダ内のファイルを読み取れません。") from error
    for directory, dirs, names in os.walk(source, followlinks=False, onerror=walk_error):
        entries += len(dirs) + len(names)
        if entries > MAX_FOLDER_ENTRIES:
            raise HTTPException(413, "フォルダ内の項目は10,000件以内にしてください。")
        for name in sorted(dirs + names):
            path = Path(directory) / name
            if path.is_symlink():
                raise HTTPException(422, "シンボリックリンクを含むフォルダは取り込めません。")
            if path.suffix.lower() in {".wav", ".txt"} and path.is_file():
                files.append(path)
                if len(files) > MAX_FOLDER_FILES:
                    raise HTTPException(413, "WAV と TXT の合計は500ファイル以内にしてください。")
    return sorted(files, key=lambda path: path.relative_to(source).as_posix())


def canonical_key(relative: Path) -> str:
    return unicodedata.normalize("NFC", relative.with_suffix("").as_posix()).casefold()


def grouped_files(source: Path, paths: list[Path]) -> dict:
    groups = {}
    for path in paths:
        group = groups.setdefault(canonical_key(path.relative_to(source)), {"wav": [], "txt": []})
        group[path.suffix.lower().removeprefix(".")].append(path)
    return groups


def _validate_source_path(path: Path, source: Path) -> None:
    relative = path.relative_to(source)
    current = source
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("source became a symbolic link")
    path.resolve().relative_to(source)


def copy_source(path: Path, source: Path, destination: Path) -> int:
    try:
        _validate_source_path(path, source)
        before = path.stat(follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_FILE_BYTES:
            raise ValueError("regular file of at most 200 MB required")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as incoming:
            opened = os.fstat(incoming.fileno())
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError("source changed during opening")
            _validate_source_path(path, source)
            with destination.open("xb") as output:
                count = 0
                while data := incoming.read(1024 * 1024):
                    count += len(data)
                    if count > MAX_FILE_BYTES:
                        raise ValueError("source exceeds 200 MB")
                    output.write(data)
            after = os.fstat(incoming.fileno())
            if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("source changed during copying")
        return count
    except (OSError, ValueError) as error:
        raise HTTPException(422, "入力ファイルが変更・欠損したか、安全に読み取れません。再度取り込んでください。") from error


def _copied_file(path: Path, source: Path, directory: Path) -> tuple[dict, int]:
    destination = directory / f"{uuid.uuid4().hex}{path.suffix.lower()}"
    size = copy_source(path, source, destination)
    return {"name": path.name, "relativePath": path.relative_to(source).as_posix(), "file": destination.name, "hash": digest(destination)}, size


def _folder_rows(source: Path, groups: dict, directory: Path, identifier: str) -> tuple[list, int]:
    rows = []
    total = 0
    ignored = 0
    for group in groups.values():
        if not group["wav"]:
            ignored += len(group["txt"])
            continue
        copied = {}
        for path in (*group["wav"], *group["txt"]):
            copied[path], size = _copied_file(path, source, directory)
            total += size
            if total > MAX_TOTAL_BYTES:
                raise HTTPException(413, "一度の取り込みは1GB以内にしてください。")
        for wav in group["wav"]:
            matching = [txt for txt in group["txt"] if unicodedata.normalize("NFC", txt.relative_to(source).with_suffix("").as_posix()) == unicodedata.normalize("NFC", wav.relative_to(source).with_suffix("").as_posix())]
            txt = matching[0] if len(matching) == 1 else None
            pair = {"wav": copied[wav], **({"txt": copied[txt]} if txt else {})}
            row = _row(directory, wav.stem, pair)
            blocked = len(group["wav"]) > 1 or len(group["txt"]) > 1 or bool(group["txt"] and txt is None)
            row.update(relativePath=wav.relative_to(source).as_posix(), blocked=blocked,
                       textCandidates=[path.relative_to(source).as_posix() for path in group["txt"]])
            if blocked:
                row["issues"].append("大小文字・Unicode・同名候補の対応が曖昧です。原本の名前を整理して取り込み直すか、この行を除外してください。")
            row["audioUrl"] = input_audio_url(identifier, row["id"])
            rows.append(row)
    return rows, ignored


def stage_folder(path: str) -> dict:
    requested = Path(path).expanduser()
    source = requested.resolve()
    paths = scan_folder(requested)
    try:
        if requested.is_symlink() or requested.resolve() != source:
            raise ValueError("selected folder changed")
        groups = grouped_files(source, [source / item.relative_to(requested) for item in paths])
    except (OSError, ValueError) as error:
        raise HTTPException(422, "選択フォルダが変更されています。再度取り込んでください。") from error
    if not any(group["wav"] for group in groups.values()):
        raise HTTPException(422, "フォルダ内に WAV がありません。")
    identifier = uuid.uuid4().hex
    directory = owned_path("inputs", identifier)
    directory.mkdir(parents=True)
    try:
        rows, ignored = _folder_rows(source, groups, directory, identifier)
        record = {"datasetId": identifier, "folderName": source.name, "rows": rows, "ignoredTextCount": ignored,
                  "limits": {"maxFiles": MAX_FOLDER_FILES, "maxEntries": MAX_FOLDER_ENTRIES, "maxFileBytes": MAX_FILE_BYTES, "maxTotalBytes": MAX_TOTAL_BYTES}}
        write_json(directory / "record.json", record)
        return record
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
