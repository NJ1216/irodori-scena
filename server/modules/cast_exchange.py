from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException, Response
from pydantic import BaseModel, Field
from server.modules.request_model import StrictRequestModel
from server.modules.lora_reference import LoraReference, lora_portability_warnings
from server.modules.lora_mix import LoraMix
from server.modules.project_repository import cast_mutation

from server.registry import deps

FORMAT = "irodori-scena-cast"
VERSION = 1
MAX_WAV = 25 * 1024 * 1024
MAX_ORIGINAL = 8 * 1024 * 1024
MAX_THUMBNAIL = 1024 * 1024
MAX_TOTAL = MAX_WAV + MAX_ORIGINAL + MAX_THUMBNAIL + 1024 * 1024
SESSION_TTL_SECONDS = 30 * 60
ALLOWED_FIXED = {"manifest.json", "reference.wav", "avatar-thumbnail.png"}
ALLOWED_ORIGINALS = {"avatar-original.png", "avatar-original.jpg", "avatar-original.jpeg", "avatar-original.webp"}
_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()


class CastExportRequest(StrictRequestModel):
    cast_ids: list[str] = Field(min_length=1)
    destination_dir: str
    overwrite: bool = False


class CastImportPrepareRequest(StrictRequestModel):
    paths: list[str] = Field(min_length=1)


class CastImportDecision(BaseModel):
    incoming_key: str
    action: Literal["overwrite", "skip"]


class CastImportCommitRequest(StrictRequestModel):
    session_id: str
    decisions: list[CastImportDecision] = Field(default_factory=list)


class CastImportCancelRequest(StrictRequestModel):
    session_id: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_filename(value: str) -> str:
    cleaned = "".join("_" if char in '/\\:\0' or ord(char) < 32 else char for char in value).strip(" .")
    return cleaned or "名称未設定"


def _asset_path(character: dict[str, Any], key: str) -> Path | None:
    value = str(character.get(key, ""))
    if not value:
        return None
    if key == "referenceFile":
        path = Path(value)
    elif value.startswith("/global-media/"):
        path = deps.GLOBAL_MEDIA_ROOT / value.removeprefix("/global-media/")
    elif value.startswith("/media/"):
        path = deps.MEDIA_ROOT / value.removeprefix("/media/")
    else:
        return None
    return path.resolve()


def _portable_character(character: dict[str, Any]) -> dict[str, Any]:
    keys = ("name", "profile", "profileDetails", "voiceKeywords", "voiceDesign", "imagePrompt", "imagePromptPreferences", "lora", "loraMix", "sampleText")
    return {key: character[key] for key in keys if key in character}


def _archive_bytes(character: dict[str, Any]) -> bytes:
    reference = _asset_path(character, "referenceFile") or _asset_path(character, "referenceAudioUrl")
    if reference is None or not reference.is_file():
        raise ValueError("参照WAVが見つかりません。")
    wav = reference.read_bytes()
    if len(wav) > MAX_WAV or len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("参照WAVが無効、または25 MBを超えています。")
    assets: dict[str, bytes] = {"reference.wav": wav}
    original = _asset_path(character, "avatarOriginalUrl")
    if original and original.is_file():
        suffix = original.suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            raise ValueError("原画像の形式に対応していません。")
        assets[f"avatar-original{suffix}"] = original.read_bytes()
    thumbnail = _asset_path(character, "avatarThumbnailUrl")
    if thumbnail and thumbnail.is_file():
        assets["avatar-thumbnail.png"] = thumbnail.read_bytes()
    if len(assets.get("avatar-thumbnail.png", b"")) > MAX_THUMBNAIL or any(len(data) > MAX_ORIGINAL for name, data in assets.items() if name.startswith("avatar-original.")):
        raise ValueError("画像のサイズ上限を超えています。")
    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "castId": str(character.get("id", "")),
        **_portable_character(character),
        "createdAt": character.get("createdAt", deps.now_ms()),
        "assets": {name: {"sha256": _sha256(data), "size": len(data)} for name, data in assets.items()},
    }
    with tempfile.SpooledTemporaryFile(max_size=MAX_TOTAL) as output:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":")))
            for name, data in assets.items():
                archive.writestr(name, data)
        output.seek(0)
        return output.read()


def _export_names(characters: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    result = []
    for character in characters:
        base = _safe_filename(str(character.get("name", "")))
        counts[base] = counts.get(base, 0) + 1
        suffix = "" if counts[base] == 1 else f" ({counts[base]})"
        result.append(f"{base}{suffix}.scenacast")
    return result


@deps.app.post("/api/casts/export")
def export_casts(request: CastExportRequest) -> dict[str, Any]:
    destination = Path(request.destination_dir).expanduser().resolve()
    if not destination.is_dir():
        raise HTTPException(status_code=422, detail="保存先フォルダが見つかりません。")
    by_id = {str(item.get("id", "")): item for item in deps.read_project().get("characters", []) if isinstance(item, dict)}
    characters = [by_id[cast_id] for cast_id in request.cast_ids if cast_id in by_id]
    missing = [cast_id for cast_id in request.cast_ids if cast_id not in by_id]
    names = _export_names(characters)
    collisions = [name for name in names if (destination / name).exists()]
    if collisions and not request.overwrite:
        raise HTTPException(status_code=409, detail={"code": "cast_export_conflict", "files": collisions})
    stage = Path(tempfile.mkdtemp(prefix="scena-cast-export-", dir=destination))
    backups = stage / "backups"
    results: list[dict[str, Any]] = [{"castId": item, "status": "failed", "error": "キャストが見つかりません。"} for item in missing]
    prepared: list[tuple[Path, Path, str]] = []
    try:
        for character, name in zip(characters, names, strict=True):
            try:
                staged = stage / name
                staged.write_bytes(_archive_bytes(character))
                prepared.append((staged, destination / name, str(character.get("id", ""))))
            except (OSError, ValueError, zipfile.BadZipFile) as error:
                results.append({"castId": character.get("id"), "name": character.get("name"), "status": "failed", "error": str(error)})
        backups.mkdir()
        placed: list[tuple[Path, Path | None]] = []
        try:
            for staged, target, cast_id in prepared:
                backup = backups / target.name if target.exists() else None
                if backup:
                    target.replace(backup)
                staged.replace(target)
                placed.append((target, backup))
                results.append({"castId": cast_id, "status": "exported", "path": str(target)})
        except OSError:
            for target, backup in reversed(placed):
                target.unlink(missing_ok=True)
                if backup and backup.exists():
                    backup.replace(target)
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return {"destinationDir": str(destination), "results": results, "warnings": lora_portability_warnings(characters)}


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    allowed = name in ALLOWED_FIXED or name in ALLOWED_ORIGINALS
    if not allowed or Path(name).is_absolute() or ".." in Path(name).parts or info.flag_bits & 1:
        raise ValueError("許可されていないアーカイブメンバーです。")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise ValueError("シンボリックリンクは読み込めません。")


def _read_archive(path: Path, stage: Path, incoming_key: str) -> dict[str, Any]:
    if path.suffix.lower() != ".scenacast" or not path.is_file():
        raise ValueError(".scenacastファイルではありません。")
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("重複したアーカイブメンバーがあります。")
        for info in infos:
            _validate_member(info)
        if sum(info.file_size for info in infos) > MAX_TOTAL:
            raise ValueError("展開サイズの上限を超えています。")
        if "manifest.json" not in names or "reference.wav" not in names:
            raise ValueError("manifest.jsonまたはreference.wavがありません。")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("manifest.jsonが不正です。") from error
        if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or manifest.get("version") != VERSION:
            raise ValueError("対応していないキャスト形式です。")
        assets = manifest.get("assets")
        if not isinstance(assets, dict) or set(assets) != set(names) - {"manifest.json"}:
            raise ValueError("資産一覧が一致しません。")
        target = stage / incoming_key
        target.mkdir()
        read_assets: dict[str, bytes] = {}
        for name in assets:
            data = archive.read(name)
            limit = MAX_WAV if name == "reference.wav" else MAX_THUMBNAIL if name == "avatar-thumbnail.png" else MAX_ORIGINAL
            expected = assets[name] if isinstance(assets[name], dict) else {}
            if len(data) > limit or expected.get("size") != len(data) or expected.get("sha256") != _sha256(data):
                raise ValueError(f"{name}のサイズまたはハッシュが一致しません。")
            (target / name).write_bytes(data)
            read_assets[name] = data
        wav = read_assets["reference.wav"]
        if len(wav) < 44 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
            raise ValueError("reference.wavが標準WAVではありません。")
    character = {"id": str(manifest.get("castId", "")), **{key: manifest[key] for key in _portable_character(manifest) if key in manifest}, "createdAt": manifest.get("createdAt", deps.now_ms())}
    if not character["id"] or not str(character.get("name", "")).strip():
        raise ValueError("キャストIDまたは名前がありません。")
    if character.get("loraMix") is not None:
        character["loraMix"] = LoraMix.model_validate(character["loraMix"]).model_dump()
    if character.get("lora") is not None:
        character["lora"] = LoraReference.model_validate(character["lora"]).model_dump()
    character["audioHash"] = _sha256(wav)
    return {"key": incoming_key, "sourcePath": str(path), "manifest": manifest, "character": character, "stage": str(target)}


def _content_signature(character: dict[str, Any], audio_hash: str) -> str:
    return _sha256(json.dumps({**_portable_character(character), "audioHash": audio_hash}, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())


def _existing_audio_hash(character: dict[str, Any]) -> str:
    value = str(character.get("audioHash", ""))
    if value:
        return value
    path = _asset_path(character, "referenceFile") or _asset_path(character, "referenceAudioUrl")
    return deps.audio_digest(path) if path and path.is_file() else ""


def _cleanup_expired() -> None:
    now = time.time()
    expired = []
    with _sessions_lock:
        for key, session in list(_sessions.items()):
            if now - session["created"] > SESSION_TTL_SECONDS:
                expired.append(_sessions.pop(key))
    for session in expired:
        shutil.rmtree(session["root"], ignore_errors=True)


@deps.app.post("/api/casts/import/prepare")
def prepare_cast_import(request: CastImportPrepareRequest) -> dict[str, Any]:
    _cleanup_expired()
    root = Path(tempfile.mkdtemp(prefix="scena-cast-import-"))
    existing = [item for item in deps.read_global_characters() if isinstance(item, dict)]
    valid, errors = [], []
    for index, value in enumerate(request.paths):
        key = f"incoming-{index}"
        try:
            valid.append(_read_archive(Path(value).expanduser().resolve(), root, key))
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
            errors.append({"path": value, "status": "invalid", "error": str(error)})
    selected_identity: dict[str, dict[str, Any]] = {}
    items = []
    for incoming in valid:
        character = incoming["character"]
        audio_hash = character["audioHash"]
        match = next((item for item in existing if str(item.get("id", "")) == character["id"] or _existing_audio_hash(item) == audio_hash), None)
        match = match or selected_identity.get(character["id"]) or selected_identity.get(audio_hash)
        if match and _content_signature(match, _existing_audio_hash(match)) == _content_signature(character, audio_hash):
            status = "identical"
        elif match:
            status = "conflict"
        else:
            status = "new"
            selected_identity[character["id"]] = character
            selected_identity[audio_hash] = character
        incoming.update({"status": status, "existingId": str(match.get("id", "")) if match else None})
        items.append({"key": incoming["key"], "path": incoming["sourcePath"], "status": status, "incoming": character, "existing": match})
    session_id = os.urandom(16).hex()
    with _sessions_lock:
        _sessions[session_id] = {"created": time.time(), "root": root, "items": valid}
    return {"sessionId": session_id, "items": items, "errors": errors, "expiresInSeconds": SESSION_TTL_SECONDS, "warnings": lora_portability_warnings([item["incoming"] for item in items])}


def _install_character(incoming: dict[str, Any], character_id: str, relations: dict[str, str]) -> dict[str, Any]:
    source = Path(incoming["stage"])
    target = deps.GLOBAL_MEDIA_ROOT / "characters" / deps.safe_segment(character_id)
    target.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source / "reference.wav", target / "reference.wav")
    original = next(source.glob("avatar-original.*"), None)
    if original:
        shutil.copy2(original, target / original.name)
    thumbnail = source / "avatar-thumbnail.png"
    if thumbnail.is_file():
        shutil.copy2(thumbnail, target / thumbnail.name)
    character = dict(incoming["character"])
    character["id"] = character_id
    details = deps.normalize_character_profile_details(character.get("profileDetails"))
    raw_relations = details.get("castRelations", {})
    details["castRelations"] = {relations[target_id]: value for target_id, value in raw_relations.items() if target_id in relations}
    character["profileDetails"] = details
    character.update({"scope": "global", "referenceFile": str(target / "reference.wav"), "referenceAudioUrl": deps.global_media_url(target / "reference.wav"), "audioHash": incoming["character"]["audioHash"]})
    if original:
        character["avatarOriginalUrl"] = deps.global_media_url(target / original.name)
    if thumbnail.is_file():
        character.update({"avatarThumbnailUrl": deps.global_media_url(target / thumbnail.name), "avatarUrl": deps.global_media_url(target / thumbnail.name)})
    return character


@deps.app.post("/api/casts/import/commit")
@cast_mutation
def commit_cast_import(request: CastImportCommitRequest) -> dict[str, Any]:
    with _sessions_lock:
        session = _sessions.pop(request.session_id, None)
    if not session:
        raise HTTPException(status_code=410, detail="インポートセッションが期限切れか、すでに終了しています。")
    decisions = {item.incoming_key: item.action for item in request.decisions}
    conflicts = [item for item in session["items"] if item["status"] == "conflict"]
    if any(item["key"] not in decisions for item in conflicts):
        with _sessions_lock:
            _sessions[request.session_id] = session
        raise HTTPException(status_code=422, detail="すべての競合について上書きまたはスキップを選択してください。")
    before = deps.read_global_characters()
    library = [dict(item) for item in before]
    backup_root = Path(tempfile.mkdtemp(prefix="scena-cast-rollback-"))
    changed_ids: list[str] = []
    id_map = {str(item.get("id", "")): str(item.get("id", "")) for item in library}
    for item in session["items"]:
        if item["status"] == "new":
            incoming_id = item["character"]["id"]
            actual_id = incoming_id if incoming_id not in id_map else deps.new_id("character")
            id_map[incoming_id] = actual_id
        elif item.get("existingId"):
            id_map[item["character"]["id"]] = item["existingId"]
    applied, skipped = [], []
    try:
        for item in session["items"]:
            if item["status"] == "identical" or (item["status"] == "conflict" and decisions[item["key"]] == "skip"):
                skipped.append({"key": item["key"], "status": item["status"]})
                continue
            actual_id = id_map[item["character"]["id"]]
            old_index = next((index for index, value in enumerate(library) if str(value.get("id", "")) == actual_id), None)
            old_media = deps.GLOBAL_MEDIA_ROOT / "characters" / deps.safe_segment(actual_id)
            changed_ids.append(actual_id)
            if old_media.exists():
                shutil.copytree(old_media, backup_root / actual_id)
                shutil.rmtree(old_media)
            character = _install_character(item, actual_id, id_map)
            if old_index is None:
                library.append(character)
            else:
                library[old_index] = character
            applied.append({"key": item["key"], "castId": actual_id, "status": "overwritten" if old_index is not None else "imported"})
        deps.write_global_characters(library)
    except Exception:
        for character_id in changed_ids:
            target = deps.GLOBAL_MEDIA_ROOT / "characters" / deps.safe_segment(character_id)
            shutil.rmtree(target, ignore_errors=True)
            backup = backup_root / character_id
            if backup.exists():
                shutil.copytree(backup, target)
        deps.write_global_characters(before)
        raise
    finally:
        shutil.rmtree(backup_root, ignore_errors=True)
        shutil.rmtree(session["root"], ignore_errors=True)
    return {"applied": applied, "skipped": skipped, "project": deps.read_project()}


@deps.app.post("/api/casts/import/cancel")
def cancel_cast_import(request: CastImportCancelRequest) -> dict[str, bool]:
    with _sessions_lock:
        session = _sessions.pop(request.session_id, None)
    if session:
        shutil.rmtree(session["root"], ignore_errors=True)
    return {"cancelled": True}


@deps.app.get("/api/casts/import/{session_id}/media/{incoming_key}/{asset_name}")
def cast_import_media(session_id: str, incoming_key: str, asset_name: str) -> Response:
    with _sessions_lock:
        session = _sessions.get(session_id)
    if not session or time.time() - session["created"] > SESSION_TTL_SECONDS:
        raise HTTPException(status_code=410, detail="インポートセッションが期限切れです。")
    item = next((value for value in session["items"] if value["key"] == incoming_key), None)
    if not item or asset_name not in {"reference.wav", "avatar-thumbnail.png"}:
        raise HTTPException(status_code=404, detail="比較用資産がありません。")
    path = Path(item["stage"]) / asset_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="比較用資産がありません。")
    media_type = "audio/wav" if asset_name == "reference.wav" else "image/png"
    return Response(path.read_bytes(), media_type=media_type, headers={"Cache-Control": "no-store"})


deps.register(__name__, ["CastExportRequest", "CastImportPrepareRequest", "CastImportCommitRequest", "CastImportCancelRequest"])
