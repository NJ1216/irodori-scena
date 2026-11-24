from __future__ import annotations
from server.modules.lora_mix import apply_mix_patch

from server.app_deps import secrets, shutil, b64decode, Path, Any, HTTPException
from server.registry import deps
from server.modules.character_deletion_routes import delete_character  # noqa: F401
from server.modules.pronunciation_dictionary import dictionary_transaction
from server.modules.voice_design import VOICE_DESIGN_AUDIO_QUALITY_SUFFIX, inference_caption  # noqa: F401
from server.modules.voice_design import selected_voice_design_candidates, voice_design_keywords
from server.modules.voice_design_generation import generate_candidate_clips

_voice_design_inference_caption = inference_caption


def _discard_candidate_wavs(paths: list[Path]) -> None:
    deps.clear_voice_candidates({"candidates": [{"file": str(path)} for path in paths]})


@deps.app.post("/api/characters/candidates")
def create_candidates(request: deps.CandidateRequest) -> dict[str, Any]:
    deps.require_tts_available()
    capabilities = deps.selected_model_capabilities()
    if capabilities is not None and not capabilities["voiceDesign"]:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "tts_model_unsupported_voice_design",
                "message": "選択中の音声モデルはVoiceDesignに対応していません。音声モデルを切り替えてください。",
            },
        )
    if request.kind == "emotion" and capabilities is not None and not capabilities["combinedReferenceCaption"]:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "tts_model_unsupported_combined_voice_design",
                "message": "選択中の音声モデルは参照音声とVoiceDesignの併用に対応していません。caption単独のVoiceDesignは利用できます。",
            },
        )
    with deps.VOICE_CANDIDATE_GENERATION_LOCK:
        generation_epoch = deps.VOICE_CANDIDATE_GENERATION_EPOCH
    project = deps.read_project()
    keywords = (
        voice_design_keywords(request.voice_design.model_dump()) if request.voice_design else request.keywords.strip()
    )
    reference = None
    if request.kind == "emotion":
        baseline = next(
            (item for item in project.get("candidates", []) if item.get("id") == request.reference_candidate_id), None
        )
        if baseline is None or baseline.get("kind", "baseline") != "baseline":
            raise HTTPException(status_code=422, detail="先に選択した基準ボイスが必要です。")
        reference = Path(str(baseline.get("file", ""))).resolve()
        if not reference.is_file():
            raise HTTPException(status_code=404, detail="選択した基準ボイスのWAVが見つかりません。")
        speech_rate = float(baseline.get("speechRate", 1.0))
        text_cfg = float(baseline.get("textCfg", request.text_cfg))
        voice_cfg = float(baseline.get("voiceCfg", request.voice_cfg))
        caption_cfg = float(baseline.get("captionCfg", request.caption_cfg))
    else:
        speech_rate = request.speech_rate
        text_cfg, voice_cfg, caption_cfg = request.text_cfg, request.voice_cfg, request.caption_cfg
    capabilities = deps.model_capabilities_for_selection(project.get("ttsSelection")) or {}
    supports_runtime_cfg = capabilities.get("supportsRuntimeCfg", True)
    effective_steps = int(capabilities.get("fixedSteps") or 40)
    cfg_settings = ({"textCfg": text_cfg, "voiceCfg": voice_cfg, "captionCfg": caption_cfg} if supports_runtime_cfg else {})
    project_settings = project.get("settings", {})
    sampling_project_settings = project_settings if supports_runtime_cfg else {key: value for key, value in project_settings.items() if key not in {"textCfg", "voiceCfg", "captionCfg", "quality"}}
    candidates: list[dict[str, Any]] = []
    batch_id = deps.new_id("candidate_batch")
    seed = secrets.randbelow(2000000000)
    clips = generate_candidate_clips(
        deps.run_irodori,
        deps.validate_voice_design_clip,
        _discard_candidate_wavs,
        count=request.count,
        text=deps.apply_pronunciation_dictionary(request.sample_text.strip(), ""),
        caption=inference_caption(keywords),
        output=deps.MEDIA_ROOT / "candidates" / f"{batch_id}.wav",
        seed=seed,
        ref_wav=reference,
        quality="quality",
        generation_settings={
            **sampling_project_settings,
            "steps": effective_steps,
            "speechRate": speech_rate,
            **cfg_settings,
        },
    )
    generated = [path for path, _duration in clips]
    with deps.VOICE_CANDIDATE_GENERATION_LOCK:
        if generation_epoch != deps.VOICE_CANDIDATE_GENERATION_EPOCH:
            deps.clear_voice_candidates({"candidates": [{"file": str(path)} for path in generated]})
            return {"candidates": []}
    for index, (output, duration) in enumerate(clips, start=1):
        candidate_id = deps.new_id("candidate")
        candidate = {
            "id": candidate_id,
            "keywords": keywords,
            "voiceDesign": request.voice_design.model_dump() if request.voice_design else None,
            "sampleText": request.sample_text.strip(),
            "kind": request.kind,
            "emotion": request.emotion,
            "referenceCandidateId": request.reference_candidate_id,
            "durationSeconds": round(duration, 2),
            "speechRate": speech_rate,
            "seed": seed + index - 1,
            "audioUrl": deps.media_url(output),
            "file": str(output),
            "createdAt": deps.now_ms(),
        }
        if supports_runtime_cfg:
            candidate.update(cfg_settings)
        candidates.append(candidate)
    with deps.VOICE_CANDIDATE_GENERATION_LOCK:
        if generation_epoch != deps.VOICE_CANDIDATE_GENERATION_EPOCH:
            deps.clear_voice_candidates({"candidates": [{"file": str(path)} for path in generated]})
            return {"candidates": []}
        latest_project = deps.read_project()
        latest_project["candidates"] = latest_project.get("candidates", []) + candidates
        deps.write_project(latest_project)
    return {"candidates": candidates}


@deps.app.post("/api/characters/voice-design/save")
def save_voice_design(request: deps.SaveVoiceDesignRequest) -> dict[str, Any]:
    project = deps.read_project()
    keywords = (
        voice_design_keywords(request.voice_design.model_dump())
        if request.voice_design
        else request.voice_keywords.strip()
    )
    clips = selected_voice_design_candidates(project, request)
    paths = [Path(str(item.get("file", ""))).resolve() for item in clips]
    if not all(path.is_file() for path in paths):
        raise HTTPException(status_code=404, detail="選択したVoiceDesign候補のWAVが見つかりません。")
    for path in paths:
        deps.validate_voice_design_clip(path)
    audio = deps.concatenate_reference_wavs(paths)
    if request.character_id:
        result = _apply_reference_audio(
            request.character_id,
            audio,
            voice_keywords=keywords,
            voice_design=request.voice_design.model_dump() if request.voice_design else None,
            sample_text=str(clips[0].get("sampleText") or ""),
        )
    else:
        character_id = deps.new_id("character")
        target = deps.GLOBAL_MEDIA_ROOT / "characters" / deps.safe_segment(character_id) / "reference.wav"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(audio)
        character = deps.character_record(
            character_id=character_id,
            name=request.name,
            profile=request.profile,
            voice_keywords=keywords,
            reference=target,
            scope="global",
        )
        character["sampleText"] = str(clips[0].get("sampleText") or "")
        if request.voice_design is not None:
            character["voiceDesign"] = request.voice_design.model_dump()
        deps.write_global_characters(deps.read_global_characters() + [character])
        result = {"character": character, "project": project, "invalidatedLines": 0}
    latest = deps.read_project()
    deps.clear_voice_candidates(latest)
    deps.write_project(latest)
    result["project"] = deps.read_project()
    return result


@deps.app.post("/api/characters/candidates/clear")
def clear_candidates() -> dict[str, Any]:
    with deps.VOICE_CANDIDATE_GENERATION_LOCK:
        deps.VOICE_CANDIDATE_GENERATION_EPOCH += 1
        project = deps.read_project()
        deps.clear_voice_candidates(project)
        deps.write_project(project)
        return project


@deps.app.post("/api/characters/accept")
def accept_candidate(request: deps.AcceptCandidateRequest) -> dict[str, Any]:
    project = deps.read_project()
    candidate = next((item for item in project.get("candidates", []) if item.get("id") == request.candidate_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Voice candidate not found.")
    source = Path(str(candidate["file"])).resolve()
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Candidate WAV is missing.")
    character_id = deps.new_id("character")
    target = deps.GLOBAL_MEDIA_ROOT / "characters" / deps.safe_segment(character_id) / "reference.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    global_characters = deps.read_global_characters()
    next_project = dict(project)
    next_project["candidates"] = [
        item for item in project.get("candidates", []) if item.get("id") != request.candidate_id
    ]
    try:
        # Keep the candidate playable until both metadata stores have accepted
        # the new character.  A failed registration must remain retryable.
        shutil.copy2(source, target)
        character = deps.character_record(
            character_id=character_id,
            name=request.name,
            profile=request.profile,
            voice_keywords=candidate["keywords"],
            reference=target,
            scope="global",
        )
        character["sampleText"] = str(candidate.get("sampleText") or "")
        deps.write_global_characters(global_characters + [character])
        try:
            deps.write_project(next_project)
        except Exception:
            deps.write_global_characters(global_characters)
            raise
    except Exception:
        target.unlink(missing_ok=True)
        try:
            target.parent.rmdir()
        except OSError:
            pass
        raise
    try:
        source.unlink()
    except OSError:
        # Registration is already durable. Leaving this unreferenced copy is
        # preferable to reporting a failed registration after it succeeded.
        pass
    return character


@deps.app.post("/api/characters/import")
def import_reference_wav(request: deps.ImportReferenceRequest) -> dict[str, Any]:
    try:
        audio = b64decode(request.audio_base64, validate=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="The selected file was not valid base64 audio data.") from error
    if len(audio) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Reference WAV must be 25 MB or smaller.")
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise HTTPException(status_code=422, detail="Please select a standard WAV file.")
    project = deps.read_project()
    character_id = deps.new_id("character")
    target = deps.GLOBAL_MEDIA_ROOT / "characters" / deps.safe_segment(character_id) / "reference.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(audio)
    character = deps.character_record(
        character_id=character_id,
        name=request.name,
        profile=request.profile,
        voice_keywords="手元のWAVから登録",
        reference=target,
        scope="global",
    )
    deps.write_global_characters(deps.read_global_characters() + [character])
    deps.write_project(project)
    return character


def _decode_reference_audio(value: str) -> bytes:
    try:
        audio = b64decode(value, validate=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="The selected file was not valid base64 audio data.") from error
    if len(audio) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Reference WAV must be 25 MB or smaller.")
    if len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise HTTPException(status_code=422, detail="Please select a standard WAV file.")
    return audio


@deps.app.post("/api/characters/candidates/import-reference")
def import_voice_design_reference(request: deps.ImportVoiceDesignReferenceRequest) -> dict[str, Any]:
    audio = _decode_reference_audio(request.audio_base64)
    project = deps.read_project()
    if request.kind == "emotion" and not any(
        item.get("id") == request.reference_candidate_id and item.get("kind", "baseline") == "baseline"
        for item in project.get("candidates", [])
    ):
        raise HTTPException(status_code=404, detail="The selected baseline candidate was not found.")
    candidate_id = deps.new_id("candidate")
    target = deps.MEDIA_ROOT / "candidates" / f"{deps.safe_segment(candidate_id)}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(audio)
    try:
        duration = deps.validate_voice_design_clip(target)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    candidate = {
        "id": candidate_id,
        "keywords": "読み込んだ参照ボイス",
        "sampleText": "",
        "kind": request.kind,
        "emotion": request.emotion,
        "referenceCandidateId": request.reference_candidate_id,
        "durationSeconds": round(duration, 2),
        "seed": 0,
        "audioUrl": deps.media_url(target),
        "file": str(target),
        "createdAt": deps.now_ms(),
    }
    project["candidates"] = [*project.get("candidates", []), candidate]
    deps.write_project(project)
    return {"candidate": candidate}


def _apply_reference_audio(
    character_id: str, audio: bytes, *, voice_keywords: str | None = None, voice_design: dict[str, Any] | None = None, sample_text: str | None = None
) -> dict[str, Any]:
    project = deps.read_project()
    character = deps.find_character(project, character_id)
    update_global = character.get("scope") == "global" or deps.project_character_matches_global(character)
    root = deps.GLOBAL_MEDIA_ROOT if update_global else deps.MEDIA_ROOT
    target = root / "characters" / deps.safe_segment(character_id) / "reference.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}-{deps.new_id('update')}.tmp")
    backup = target.with_name(f".{target.name}-{deps.new_id('rollback')}.bak")
    had_reference = target.is_file()
    global_characters = deps.read_global_characters() if update_global else None
    committed = False
    backup_ready = False
    try:
        if had_reference:
            shutil.copy2(target, backup)
            backup_ready = True
        temporary.write_bytes(audio)
        temporary.replace(target)
        version = int(character.get("referenceVersion", 0)) + 1
        media_url = deps.global_media_url if update_global else deps.media_url
        fields = {
            "referenceAudioUrl": media_url(target),
            "referenceFile": str(target),
            "referenceVersion": version,
            "audioHash": deps.audio_digest(target),
            **({"voiceKeywords": voice_keywords.strip()} if voice_keywords is not None else {}),
            **({"voiceDesign": voice_design} if voice_design is not None else {}),
            **({"sampleText": sample_text} if sample_text is not None else {}),
        }
        character.update(fields)
        if global_characters is not None:
            updated_global = [dict(item) for item in global_characters]
            for item in updated_global:
                if str(item.get("id", "")) == character_id:
                    item.update(fields)
            deps.write_global_characters(updated_global)
        invalidated = 0
        for scene in project.get("scenes", []):
            for line in scene.get("lines", []):
                if str(line.get("characterId", "")) == character_id and line.get("selectedTakeId") is not None:
                    line["selectedTakeId"] = None
                    invalidated += 1
        deps.write_project(project)
        committed = True
    except Exception:
        if backup_ready:
            backup.replace(target)
        elif not had_reference:
            target.unlink(missing_ok=True)
        if global_characters is not None:
            try:
                deps.write_global_characters(global_characters)
            except Exception:
                pass
        raise
    finally:
        temporary.unlink(missing_ok=True)
        if committed or not backup_ready:
            backup.unlink(missing_ok=True)
    return {"character": character, "project": deps.read_project(), "invalidatedLines": invalidated}


@deps.app.put("/api/characters/{character_id}/reference")
def update_character_reference(character_id: str, request: deps.UpdateReferenceRequest) -> dict[str, Any]:
    return _apply_reference_audio(character_id, _decode_reference_audio(request.audio_base64))


@deps.app.post("/api/characters/{character_id}/reference/candidate")
def apply_candidate_reference(character_id: str, request: deps.ApplyCandidateReferenceRequest) -> dict[str, Any]:
    project = deps.read_project()
    candidate = next((item for item in project.get("candidates", []) if item.get("id") == request.candidate_id), None)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Voice candidate not found.")
    source = Path(str(candidate.get("file", ""))).resolve()
    if not source.is_file():
        raise HTTPException(status_code=404, detail="Candidate WAV is missing.")
    return _apply_reference_audio(
        character_id,
        source.read_bytes(),
        voice_keywords=str(candidate.get("keywords", "")),
        sample_text=str(candidate.get("sampleText") or ""),
    )


@deps.app.patch("/api/characters/{character_id}")
@dictionary_transaction
def update_character(character_id: str, request: deps.UpdateCharacterRequest) -> dict[str, Any]:
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Character name cannot be blank.")
    project = deps.read_project()
    character = deps.find_character(project, character_id)
    update_global = character.get("scope") == "global" or deps.project_character_matches_global(character)
    apply_mix_patch(character, request)
    character["name"] = name
    character["profile"] = request.profile.strip()
    character["voiceKeywords"] = request.voice_keywords.strip()
    if request.image_prompt is not None:
        character["imagePrompt"] = request.image_prompt.strip()
    if request.image_prompt_preferences is not None:
        character["imagePromptPreferences"] = request.image_prompt_preferences.model_dump()
    if request.profile_details is not None:
        character["profileDetails"] = deps.normalize_character_profile_details(request.profile_details)
    global_characters = deps.read_global_characters() if update_global else None
    pronunciations = deps.read_pronunciation_dictionary()
    if global_characters is not None:
        updated = []
        for item in global_characters:
            if item.get("id") == character_id:
                next_item = dict(item)
                next_item.update(
                    {
                        "lora": character.get("lora"),
                        "loraMix": character.get("loraMix"),
                        "name": character["name"],
                        "profile": character["profile"],
                        "profileDetails": character.get("profileDetails", {}),
                        "voiceKeywords": character["voiceKeywords"],
                        "imagePrompt": character.get("imagePrompt", ""),
                        "imagePromptPreferences": character.get("imagePromptPreferences", {}),
                    }
                )
                updated.append(next_item)
            else:
                updated.append(item)
    try:
        if global_characters is not None:
            deps.write_global_characters(updated)
        deps.sync_character_pronunciations(character)
        deps.write_project(project)
    except Exception:
        if global_characters is not None:
            try:
                deps.write_global_characters(global_characters)
            except Exception:
                pass
        try:
            deps.write_pronunciation_dictionary(pronunciations)
        except Exception:
            pass
        raise
    project_id = str(project.get("id", "default"))
    deps.invalidate_cast_context("global" if update_global else "project", character_id, project_id)
    if update_global and character.get("scope") != "global":
        deps.invalidate_cast_context("project", character_id, project_id)
    return character



deps.register(
    __name__,
    [
        "accept_candidate",
        "apply_candidate_reference",
        "clear_candidates",
        "create_candidates",
        "import_reference_wav",
        "import_voice_design_reference",
        "save_voice_design",
        "update_character",
        "update_character_reference",
    ],
)
