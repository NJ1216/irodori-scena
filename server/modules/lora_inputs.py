"""Freeze uploaded WAV/TXT bytes before review or training."""
from __future__ import annotations
import base64
import binascii
import io
from pathlib import Path
import re
import shutil
import uuid
import wave
from fastapi import HTTPException
from server.modules.lora_storage import digest, owned_path, write_json, read_record

MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024


def _file_bytes(item: dict) -> tuple[str, bytes]:
    name = str(item.get("name", ""))
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(422, "ファイル名が不正です。")
    if not name.lower().endswith((".wav", ".txt")):
        raise HTTPException(422, "WAV と TXT のみ取り込めます。")
    encoded = item.get("dataBase64", "")
    if not isinstance(encoded, str) or len(encoded) > (MAX_FILE_BYTES * 4 // 3 + 8):
        raise HTTPException(413, "入力ファイルが大きすぎます。")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as error:
        raise HTTPException(422, "ファイルデータが不正です。") from error
    return name, data


def _wav_info(data: bytes) -> tuple[float | None, list[str]]:
    try:
        with wave.open(io.BytesIO(data)) as wav:
            duration = wav.getnframes() / wav.getframerate()
            if wav.getnchannels() not in {1, 2} or wav.getsampwidth() not in {2, 3, 4} or duration <= 0:
                raise ValueError("unsupported PCM")
            if duration > 120:
                return duration, ["WAV は120秒以内にしてください。"]
            expected = wav.getnframes() * wav.getnchannels() * wav.getsampwidth()
            if len(wav.readframes(wav.getnframes())) != expected:
                raise ValueError("truncated PCM")
            return duration, []
    except (wave.Error, ValueError, EOFError, ZeroDivisionError):
        return None, ["PCM WAV として読めません。"]


def stage_inputs(files: list[dict]) -> dict:
    if not files or len(files) > 500:
        raise HTTPException(422, "1〜500件の WAV/TXT を選択してください。")
    identifier = uuid.uuid4().hex
    directory = owned_path("inputs", identifier)
    directory.mkdir(parents=True)
    groups, total = {}, 0
    try:
        for item in files:
            name, data = _file_bytes(item)
            total += len(data)
            if total > MAX_TOTAL_BYTES:
                raise HTTPException(413, "一度の取り込みは1GB以内にしてください。")
            stem, extension = name.rsplit(".", 1)
            group = groups.setdefault(stem, {})
            if extension.lower() in group:
                raise HTTPException(422, f"同名ファイルが重複しています: {name}")
            target = directory / f"{uuid.uuid4().hex}.{extension.lower()}"
            target.write_bytes(data)
            group[extension.lower()] = {"name": name, "file": target.name, "hash": digest(target)}
        rows = [_row(directory, stem, group) for stem, group in groups.items()]
        for row in rows:
            if row["source"].get("wav"):
                row["audioUrl"] = input_audio_url(identifier, row["id"])
        record = {"datasetId": identifier, "rows": rows}
        write_json(directory / "record.json", record)
        return record
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def _row(directory, stem, group) -> dict:
    wav, txt = group.get("wav"), group.get("txt")
    duration, issues = _wav_info((directory / wav["file"]).read_bytes()) if wav else (None, ["WAV がありません。"])
    text = ""
    if txt:
        try:
            text = (directory / txt["file"]).read_text(encoding="utf-8-sig")
        except UnicodeError:
            issues.append("TXT は UTF-8 で保存してください。")
    else:
        issues.append("TXT がありません。本文を入力してください。")
    return {"id": uuid.uuid4().hex, "wavName": wav["name"] if wav else None,
            "textName": txt["name"] if txt else None, "text": text, "caption": "", "speakerId": "speaker-1",
            "durationSeconds": duration, "issues": issues, "source": group, "label": stem}


def freeze_rows(dataset_id: str, edits: list[dict], target, *, max_seconds: float | None = 120) -> list[dict]:
    record = read_record("inputs", dataset_id)
    originals = {row["id"]: row for row in record["rows"]}
    if len(edits) != len(originals) or {row.get("id") for row in edits} != set(originals):
        raise HTTPException(422, "すべての入力行を確認してください。")
    rows = []
    for index, edit in enumerate(edits):
        original = originals[edit["id"]]
        if edit.get("excluded") is True:
            continue
        if original.get("blocked") is True:
            raise HTTPException(422, "対応が曖昧な入力行は学習できません。取り込み直すか除外してください。")
        wav = original["source"].get("wav")
        if not wav or original["durationSeconds"] is None or original["durationSeconds"] > 120:
            raise HTTPException(422, "対応する有効な WAV が必要です。取り込みを修正してください。")
        if max_seconds is not None and original["durationSeconds"] > max_seconds + 1e-6:
            raise HTTPException(422, f"{original['wavName']} は設定上限 {max_seconds} 秒を超えています。WAV と対応本文を分割するか、詳細設定の上限を増やしてください。")
        text, speaker = str(edit.get("text", "")), str(edit.get("speakerId", ""))
        if not text.strip() or not speaker.strip() or len(text) > 10000 or len(speaker) > 200:
            raise HTTPException(422, "各行の本文と話者 ID を入力してください。")
        source = owned_path("inputs", dataset_id) / wav["file"]
        if digest(source) != wav["hash"]:
            raise HTTPException(409, "固定済み入力が変更されています。再度取り込んでください。")
        output = target / f"sample-{index}.wav"
        shutil.copyfile(source, output)
        rows.append({"wav": output.name, "wavHash": wav["hash"], "text": text,
                     "caption": str(edit.get("caption", "")), "speaker_id": speaker,
                     "durationSeconds": original["durationSeconds"]})
    if len(rows) < 2:
        raise HTTPException(422, "有効な WAV と本文を2組以上用意してください。")
    return rows


def input_audio_url(dataset_id: str, row_id: str) -> str:
    return f"/api/lora/inputs/{dataset_id}/rows/{row_id}/audio"


def input_audio_path(dataset_id: str, row_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", row_id):
        raise HTTPException(422, "入力行 ID が不正です。")
    record = read_record("inputs", dataset_id)
    row = next((item for item in record["rows"] if item.get("id") == row_id), None)
    wav = ((row or {}).get("source") or {}).get("wav")
    if not wav or not re.fullmatch(r"[a-f0-9]{32}\.wav", str(wav.get("file", ""))):
        raise HTTPException(404, "入力 WAV がありません。")
    directory = owned_path("inputs", dataset_id).resolve()
    path = directory / wav["file"]
    try:
        if path.is_symlink() or path.resolve().parent != directory or not path.is_file() or digest(path) != wav["hash"]:
            raise ValueError("staged input changed")
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(409, "固定済み入力が変更されています。再度取り込んでください。") from error
    return path
