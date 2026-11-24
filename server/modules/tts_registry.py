from __future__ import annotations

import hashlib
from server.app_deps import json, shutil, time, Path, Any, HTTPException
from server.modules.tts_mlx_fp32 import add_local_fp32_variants
from server.modules.tts_disk_usage import refresh_external_model_disk_usage
from server.modules.tts_catalog import ENGINE_COMMIT, ENGINE_REPO, MLX_FP16_VARIANT_ID, PYTORCH_FP32_VARIANT_ID, VERIFIED_VRAM_REQUIREMENTS, tts_catalog, validate_tts_catalog as _validate_tts_catalog
from server.modules.tts_variant_files import remove_variant_files
from server.modules.tts_mlx_variants import MLX_RUNTIMES, mlx_engine_id
from server.registry import deps
from server.modules.llm_runtime_binding import serialized
from server.modules.lora_resource_guard import require_runtime_available

def validate_tts_catalog(catalog: dict[str, Any], *, signature_verified: bool) -> dict[str, Any]:
    """Compatibility export for callers of the former registry-owned validator."""
    return _validate_tts_catalog(catalog, signature_verified=signature_verified)
def _empty_registry() -> dict[str, Any]:
    return {"version": 3, "defaultEngineId": None, "defaultModelId": None, "engines": [], "models": [], "libraries": []}
def _external_card_id(path: Path) -> str:
    return f"external:{hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]}"
def write_tts_registry(registry: dict[str, Any]) -> None:
    deps.TTS_ASSETS_ROOT.mkdir(parents=True, exist_ok=True)
    temporary = deps.TTS_REGISTRY_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(deps.TTS_REGISTRY_FILE)


def read_tts_registry() -> dict[str, Any]:
    registry = _empty_registry()
    try:
        loaded = json.loads(deps.TTS_REGISTRY_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            registry.update(loaded)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    if not isinstance(registry.get("engines"), list):
        registry["engines"] = []
    if not isinstance(registry.get("models"), list):
        registry["models"] = []
    if not isinstance(registry.get("libraries"), list):
        registry["libraries"] = []
    changed = registry.get("version") != 3
    for card in registry["models"]:
        if not isinstance(card.get("installedVariants"), list):
            card["installedVariants"] = [{
                "id": PYTORCH_FP32_VARIANT_ID, "precision": "FP32", "backend": "pytorch",
                "repo": card.get("repo"), "revision": card.get("revision"), "path": card.get("path"),
                "diskBytes": card.get("diskBytes"), "optimizationProfile": card.get("optimizationProfile", "pytorch-fp32"),
            }]
            card["activeVariantId"] = PYTORCH_FP32_VARIANT_ID
            changed = True
        elif not card.get("activeVariantId") and card["installedVariants"]:
            card["activeVariantId"] = card["installedVariants"][0].get("id")
            changed = True
    registry["version"] = 3
    if changed and deps.TTS_REGISTRY_FILE.exists():
        write_tts_registry(registry)
    add_local_fp32_variants(registry)
    return registry


def _active_variant(model: dict[str, Any] | None) -> dict[str, Any] | None:
    if not model:
        return None
    variants = model.get("installedVariants") or []
    if model.get("activeVariantId") == "mlx-fp32":
        return next((item for item in variants if item.get("id") == "mlx-fp32"), None)
    return next((item for item in variants if item.get("id") == model.get("activeVariantId")), None) or (variants[0] if variants else None)


def ensure_tts_storage() -> None:
    for directory in (
        deps.TTS_ENGINES_ROOT, deps.TTS_ENVIRONMENTS_ROOT, deps.TTS_MODELS_ROOT,
        deps.TTS_CODECS_ROOT, deps.TTS_DOWNLOADS_ROOT,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    registry = read_tts_registry()
    legacy = str(deps.read_connection_settings().get("engineDir", "")).strip()
    migrated_id = next((card.get("id") for card in registry["engines"] if card.get("path") == legacy), None)
    if legacy and not migrated_id:
        path = Path(legacy).expanduser()
        card_id = _external_card_id(path)
        registry["engines"].append({
            "id": card_id, "displayName": path.name or "外部 Irodori-TTS", "source": "external",
            "repo": None, "commit": None, "path": str(path.resolve()), "diskBytes": None,
            "verification": "unverified", "installedAt": int(time.time()),
        })
        registry["defaultEngineId"] = registry["defaultEngineId"] or card_id
        write_tts_registry(registry)
        migrated_id = card_id
def project_tts_selection() -> dict[str, Any] | None:
    """Compatibility projection; TTS selection is no longer project-owned."""
    return effective_tts_selection()


def effective_tts_selection(registry: dict[str, Any] | None = None) -> dict[str, Any] | None:
    registry = registry or read_tts_registry()
    model = next((item for item in registry["models"] if item.get("id") == registry.get("defaultModelId")), None)
    engine = next((item for item in registry["engines"] if item.get("id") == registry.get("defaultEngineId")), None)
    if model and model.get("libraryId"):
        engine_identity = {"repo": ENGINE_REPO, "commit": ENGINE_COMMIT}
    elif engine:
        engine_identity = {"repo": engine.get("repo"), "commit": engine.get("commit"),
                           "externalId": engine.get("id") if engine.get("source") == "external" else None}
    else:
        return None
    return {"engine": engine_identity,
            "model": {"repo": model.get("repo"), "revision": model.get("revision")} if model else None,
            "codecRevision": model.get("codecRevision") if model else None}


def selected_tts_runtime() -> dict[str, Any] | None:
    registry = read_tts_registry()
    selection = effective_tts_selection(registry)
    engine_identity = (selection or {}).get("engine") or {}
    model_identity = (selection or {}).get("model") or {}
    engine = next((card for card in registry["engines"] if
                   card.get("id") == engine_identity.get("externalId") or
                   card.get("repo") == engine_identity.get("repo") and card.get("commit") == engine_identity.get("commit")), None)
    model = next((card for card in registry["models"] if
                  card.get("repo") == model_identity.get("repo") and card.get("revision") == model_identity.get("revision")), None)
    variant = _active_variant(model)
    if model and model.get("activeVariantId") == "mlx-fp32" and variant is None:
        return None
    if variant and variant.get("backend") == "mlx":
        engine = next((card for card in registry["engines"] if card.get("id") == mlx_engine_id(variant)), None)
    elif model and model.get("source") == "managed":
        catalog_model = next((item for item in tts_catalog()["models"] if item.get("id") == model.get("id")), {})
        supported = set(catalog_model.get("supportedEngineIds", []))
        engine = next((card for card in registry["engines"] if card.get("id") in supported), engine)
    if model and model.get("libraryId"):
        library = next((item for item in registry["libraries"] if item.get("id") == model.get("libraryId")), None)
        if library:
            if not Path(str(library.get("enginePath", ""))).is_dir() or not Path(str(library.get("pythonPath", ""))).is_file():
                return None
            engine = {"id": library["engineId"], "source": "external-library", "path": library["enginePath"],
                      "pythonPath": library["pythonPath"], "libraryId": library["id"],
                      "repo": ENGINE_REPO, "commit": library.get("engineCommit")}
    if engine is None:
        return None
    if model is not None:
        model = dict(model)
        model.update(baseModelRepo=model.get("repo"), baseModelRevision=model.get("revision"))
        variant = _active_variant(model)
        if variant:
            model.update({
                "path": variant.get("path", model.get("path")), "repo": variant.get("repo", model.get("repo")),
                "revision": variant.get("revision", model.get("revision")), "backend": variant.get("backend", "pytorch"),
                "precision": variant.get("precision", "FP32"), "variantId": variant.get("id"),
                "optimizationProfile": variant.get("optimizationProfile", model.get("optimizationProfile")),
                "codecPath": variant.get("codecPath", model.get("codecPath")),
                "computePrecision": variant.get("computePrecision", "fp32"),
                "checkpointFile": variant.get("checkpointFile", "model.safetensors"),
                "quantization": variant.get("quantization"),
                "mlxAssetsPath": variant.get("mlxAssetsPath"),
                "mlxAssetsRepo": variant.get("mlxAssetsRepo"),
                "mlxAssetsRevision": variant.get("mlxAssetsRevision"),
            })
            if variant.get("pythonPath") and engine is not None:
                engine = {**engine, "pythonPath": variant["pythonPath"]}
        required_vram = VERIFIED_VRAM_REQUIREMENTS.get(str(model.get("revision")))
        if required_vram is not None:
            model["requiredVramBytes"] = required_vram
    return {"engine": engine, "model": model}


def model_capabilities_for_selection(selection: dict[str, Any] | None) -> dict[str, Any] | None:
    selection = selection or {}
    identity = selection.get("model") or {}
    item = next((entry for entry in tts_catalog()["models"] if entry.get("repo") == identity.get("repo") and entry.get("revision") == identity.get("revision")), None)
    if item is None:
        return None
    return {key: item[key] for key in ("generation", "referenceVoice", "voiceDesign", "combinedReferenceCaption", "legacy", "recommendedOrder", "flowParameterization", "fixedSteps", "supportsRuntimeCfg", "supportsQualityPresets")}


def selected_model_capabilities() -> dict[str, Any] | None:
    return model_capabilities_for_selection(effective_tts_selection())


def tts_registry_view() -> dict[str, Any]:
    ensure_tts_storage()
    registry = read_tts_registry()
    selection = effective_tts_selection(registry)
    runtime = selected_tts_runtime()
    missing = []
    if selection and runtime is None:
        missing.append("engine")
    if selection and selection.get("model") and (runtime is None or runtime.get("model") is None):
        missing.append("model")
    cache_changed = False
    catalog_models = {item["id"]: item for item in tts_catalog()["models"]}
    for model in registry["models"]:
        catalog_model = catalog_models.get(model.get("id"))
        if catalog_model:
            for key in ("author", "releasedAt", "tagline", "description"):
                if model.get(key) != catalog_model.get(key):
                    model[key] = catalog_model.get(key)
                    cache_changed = True
        cache_changed = refresh_external_model_disk_usage(model) or cache_changed
    for library in registry["libraries"]:
        library["available"] = Path(str(library.get("enginePath", ""))).is_dir() and Path(str(library.get("pythonPath", ""))).is_file()
        library["modelCount"] = sum(model.get("libraryId") == library.get("id") for model in registry["models"])
    if cache_changed:
        write_tts_registry(registry)
    active_model = next((item.get("id") for item in registry["models"]
                         if selection and selection.get("model")
                         and item.get("repo") == selection["model"].get("repo")
                         and item.get("revision") == selection["model"].get("revision")), None)
    return {**registry, "projectSelection": None, "activeModelId": active_model,
            "missingProjectAssets": missing, "selectedModelCapabilities": selected_model_capabilities()}


def _resolved_engine_id(registry: dict[str, Any], model_id: str | None, engine_id: str | None) -> str:
    if engine_id:
        return engine_id
    if not model_id:
        raise HTTPException(status_code=422, detail="音声モデルを選択してください。")
    model = next((item for item in tts_catalog()["models"] if item["id"] == model_id), None)
    installed_model = next((item for item in registry["models"] if item.get("id") == model_id), None)
    if (_active_variant(installed_model) or {}).get("backend") == "mlx":
        return mlx_engine_id(_active_variant(installed_model) or {})
    if installed_model and installed_model.get("engineId"):
        return str(installed_model["engineId"])
    installed_ids = {item.get("id") for item in registry["engines"]}
    resolved = next((item for item in (model or {}).get("supportedEngineIds", []) if item in installed_ids), None)
    if not resolved:
        raise HTTPException(status_code=409, detail="この音声モデルに必要なエンジンが導入されていません。モデルを追加し直してください。")
    return resolved


@serialized
def set_tts_defaults(engine_id: str | None, model_id: str | None) -> dict[str, Any]:
    require_runtime_available()
    if deps.INFERENCE_SYNTHESIS_LOCK.locked() or deps.active_export_job():
        raise HTTPException(status_code=409, detail="音声生成・エクスポート中は構成を切り替えられません。")
    registry = read_tts_registry()
    engine_id = _resolved_engine_id(registry, model_id, engine_id)
    external_model = next((item for item in registry["models"] if item.get("id") == model_id and item.get("libraryId")), None)
    if not external_model:
        _require_card(registry["engines"], engine_id, "エンジン")
    if model_id:
        _require_card(registry["models"], model_id, "モデル")
        _require_compatible(engine_id, model_id)
    registry["defaultEngineId"], registry["defaultModelId"] = engine_id, model_id
    write_tts_registry(registry)
    deps.shutdown_inference_worker()
    return tts_registry_view()


def set_project_tts_selection(engine_id: str | None, model_id: str | None) -> dict[str, Any]:
    set_tts_defaults(engine_id, model_id)
    return effective_tts_selection() or {}


@serialized
def set_tts_active_variant(model_id: str, variant_id: str) -> dict[str, Any]:
    require_runtime_available()
    if deps.INFERENCE_SYNTHESIS_LOCK.locked() or deps.active_export_job():
        raise HTTPException(status_code=409, detail="音声生成・エクスポート中はバリアントを切り替えられません。")
    registry = read_tts_registry()
    model = _require_card(registry["models"], model_id, "モデル")
    variant = next((item for item in model.get("installedVariants", []) if item.get("id") == variant_id), None)
    if variant is None:
        raise HTTPException(status_code=404, detail="導入済みのバリアントが見つかりません。")
    model["activeVariantId"] = variant_id
    if registry.get("defaultModelId") == model_id:
        if variant.get("backend") == "mlx":
            registry["defaultEngineId"] = mlx_engine_id(variant)
        else:
            catalog_model = next((item for item in tts_catalog()["models"] if item.get("id") == model_id), {})
            installed_engines = {item.get("id") for item in registry["engines"]}
            registry["defaultEngineId"] = next((item for item in catalog_model.get("supportedEngineIds", []) if item in installed_engines), registry.get("defaultEngineId"))
    write_tts_registry(registry)
    deps.shutdown_inference_worker()
    return tts_registry_view()


@serialized
def delete_tts_variant(model_id: str, variant_id: str) -> dict[str, Any]:
    require_runtime_available()
    registry = read_tts_registry()
    model = _require_card(registry["models"], model_id, "モデル")
    variants = model.get("installedVariants", [])
    variant = next((item for item in variants if item.get("id") == variant_id), None)
    if variant is None:
        raise HTTPException(status_code=404, detail="導入済みのバリアントが見つかりません。")
    if variant.get("derivedLocal"):
        raise HTTPException(status_code=409, detail="MLX FP32は導入済み資産を共有する構成です。削除する場合は元のFP32またはMLX FP16を選択してください。")
    if variant_id in {"pytorch-fp32", "mlx-fp16"}:
        if model.get("activeVariantId") == "mlx-fp32":
            raise HTTPException(status_code=409, detail="MLX FP32を使用中です。別の構成へ切り替えてから削除してください。")
        variants = [item for item in variants if not item.get("derivedLocal")]
        model["installedVariants"] = variants
    if len(variants) == 1:
        return delete_tts_asset("model", model_id)
    remove_variant_files(variant, variants, deps.TTS_MODELS_ROOT)
    model["installedVariants"] = [item for item in variants if item.get("id") != variant_id]
    other_variants = [entry for card in registry["models"] for entry in card.get("installedVariants", [])]
    if variant.get("backend") == "mlx" and not any(entry.get("backend") == "mlx" and mlx_engine_id(entry) == mlx_engine_id(variant) for entry in other_variants):
        mlx_engine = next((item for item in registry["engines"] if item.get("id") == mlx_engine_id(variant)), None)
        if mlx_engine and mlx_engine.get("pythonPath"):
            environment = Path(str(mlx_engine["pythonPath"])).resolve().parent.parent
            try:
                environment.relative_to(deps.TTS_ENVIRONMENTS_ROOT.resolve())
                shutil.rmtree(environment, ignore_errors=True)
            except ValueError:
                pass
        registry["engines"] = [item for item in registry["engines"] if item.get("id") != mlx_engine_id(variant)]
    if model.get("activeVariantId") == variant_id:
        remaining = sorted(model["installedVariants"], key=lambda item: {MLX_FP16_VARIANT_ID: 1, "mlx-bf16": 1, PYTORCH_FP32_VARIANT_ID: 2}.get(item.get("id"), 3))
        model["activeVariantId"] = remaining[0]["id"]
        if registry.get("defaultModelId") == model_id:
            if remaining[0].get("backend") == "mlx":
                registry["defaultEngineId"] = mlx_engine_id(remaining[0])
            else:
                catalog_model = next((item for item in tts_catalog()["models"] if item.get("id") == model_id), {})
                installed_engines = {item.get("id") for item in registry["engines"]}
                registry["defaultEngineId"] = next((item for item in catalog_model.get("supportedEngineIds", []) if item in installed_engines), registry.get("defaultEngineId"))
        deps.shutdown_inference_worker()
    active = next((item for item in model["installedVariants"] if item.get("id") == model.get("activeVariantId")), model["installedVariants"][0])
    model.update(path=active.get("path"), codecPath=active.get("codecPath"), diskBytes=sum(int(item.get("diskBytes") or 0) for item in model["installedVariants"]))
    write_tts_registry(registry)
    return tts_registry_view()


def apply_tts_defaults(project: dict[str, Any]) -> dict[str, Any]:
    project.pop("ttsSelection", None)
    return project


def register_external_engine(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.is_absolute() or not (path / "infer.py").is_file():
        raise HTTPException(status_code=422, detail="Irodori-TTS の infer.py がある絶対パスを指定してください。")
    registry = read_tts_registry()
    resolved = path.resolve()
    card_id = _external_card_id(resolved)
    if not any(item.get("id") == card_id for item in registry["engines"]):
        registry["engines"].append({
            "id": card_id, "displayName": resolved.name, "source": "external", "repo": None,
            "commit": None, "path": str(resolved), "diskBytes": None,
            "verification": "unverified", "installedAt": int(time.time()),
        })
        write_tts_registry(registry)
    return tts_registry_view()


def _remove_managed_runtime(registry: dict[str, Any]) -> None:
    for engine in registry["engines"]:
        if engine.get("source") != "managed":
            continue
        locations = ((Path(str(engine.get("path", ""))), deps.TTS_ENGINES_ROOT), (Path(str(engine.get("pythonPath", ""))).parent.parent, deps.TTS_ENVIRONMENTS_ROOT))
        for candidate, root in locations:
            try:
                candidate.resolve().relative_to(root.resolve())
            except ValueError:
                continue
            shutil.rmtree(candidate, ignore_errors=True)
    registry["engines"] = [item for item in registry["engines"] if item.get("source") != "managed"]
    registry["defaultEngineId"] = None


def _cleanup_after_final_model(registry: dict[str, Any], project: dict[str, Any], kind: str, source: str | None) -> None:
    if kind != "model" or registry["models"]:
        return
    if source == "managed":
        _remove_managed_runtime(registry)
        shutil.rmtree(deps.TTS_CODECS_ROOT, ignore_errors=True)
    registry["defaultModelId"] = None


@serialized
def delete_tts_asset(kind: str, asset_id: str) -> dict[str, Any]:
    require_runtime_available()
    registry = read_tts_registry()
    key = "engines" if kind == "engine" else "models"
    default_key = "defaultEngineId" if kind == "engine" else "defaultModelId"
    card = _require_card(registry[key], asset_id, "資産")
    external_engine = kind == "engine" and card.get("source") == "external"
    if deps.active_export_job() or deps.active_draft_job():
        raise HTTPException(status_code=409, detail="音声生成・エクスポート中は資産を削除できません。")
    was_selected = _selection_uses(effective_tts_selection(registry), kind, asset_id, registry)
    if registry.get(default_key) == asset_id:
        registry[default_key] = None
    project = deps.read_project()
    if was_selected:
        deps.shutdown_inference_worker()
    if card.get("source") == "managed":
        owned_roots = (deps.TTS_ENGINES_ROOT, deps.TTS_ENVIRONMENTS_ROOT) if kind == "engine" else (deps.TTS_MODELS_ROOT,)
        for key_name, root in zip(("path", "pythonPath"), owned_roots, strict=False):
            candidate = Path(str(card.get(key_name, ""))).resolve()
            if key_name == "pythonPath":
                candidate = candidate.parent.parent
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                continue
            if candidate.is_dir():
                shutil.rmtree(candidate)
        if kind == "model" and (codec_path := card.get("codecPath")):
            codec = Path(str(codec_path)).resolve()
            still_used = any(item.get("id") != asset_id and item.get("codecPath") == str(codec) for item in registry["models"])
            try:
                codec.relative_to(deps.TTS_CODECS_ROOT.resolve())
                if not still_used and codec.is_dir():
                    shutil.rmtree(codec)
            except ValueError:
                pass
    if external_engine:
        legacy_path = str(deps.read_connection_settings().get("engineDir", "")).strip()
        if legacy_path and Path(legacy_path).expanduser().resolve() == Path(str(card.get("path"))).resolve():
            deps.write_engine_directory("")
    registry[key] = [item for item in registry[key] if item.get("id") != asset_id]
    _cleanup_after_final_model(registry, project, kind, card.get("source"))
    write_tts_registry(registry)
    return tts_registry_view()


def verify_tts_asset(kind: str, asset_id: str) -> dict[str, Any]:
    registry = read_tts_registry()
    cards = registry["engines" if kind == "engine" else "models"]
    card = _require_card(cards, asset_id, "資産")
    if kind == "engine":
        valid = (Path(str(card.get("path", ""))) / "infer.py").is_file()
        if card.get("source") == "managed":
            valid = valid and Path(str(card.get("pythonPath", ""))).is_file()
    else:
        variants = card.get("installedVariants") or [{}]
        valid = all(
            (Path(str(variant.get("path", card.get("path", "")))) / str(variant.get("checkpointFile") or "model.safetensors")).is_file()
            and (
                (Path(str(variant.get("codecPath", card.get("codecPath", "")))) / "model.safetensors").is_file()
                if variant.get("backend") == "mlx"
                else (Path(str(variant.get("codecPath", card.get("codecPath", "")))) / "weights.pth").is_file()
            )
            for variant in variants
        )
    card["verification"] = "verified" if valid and card.get("source") == "managed" else "unverified" if valid else "failed"
    card["checkedAt"] = int(time.time())
    write_tts_registry(registry)
    return {"valid": valid, "card": card}


def _require_card(cards: list[dict[str, Any]], card_id: str | None, label: str) -> dict[str, Any]:
    card = next((item for item in cards if item.get("id") == card_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail=f"{label}が見つかりません。")
    return card


def _require_compatible(engine_id: str, model_id: str) -> None:
    if engine_id.startswith("external:") or engine_id.startswith("engine:") or engine_id in MLX_RUNTIMES:
        return
    model = next((item for item in tts_catalog()["models"] if item["id"] == model_id), None)
    if model and engine_id not in model.get("supportedEngineIds", []):
        raise HTTPException(status_code=409, detail="選択したエンジンと音声モデルには互換性がありません。")


def _selection_uses(selection: dict[str, Any] | None, kind: str, asset_id: str, registry: dict[str, Any]) -> bool:
    if not selection:
        return False
    card = next((item for item in registry["engines" if kind == "engine" else "models"] if item.get("id") == asset_id), {})
    selected = selection.get("engine" if kind == "engine" else "model") or {}
    return selected.get("externalId") == asset_id or (
        selected.get("repo") == card.get("repo") and selected.get("commit" if kind == "engine" else "revision") == card.get("commit" if kind == "engine" else "revision")
    )


deps.register(__name__, [
    "effective_tts_selection", "apply_tts_defaults", "delete_tts_asset", "delete_tts_variant", "ensure_tts_storage", "read_tts_registry", "register_external_engine",
    "model_capabilities_for_selection", "project_tts_selection", "refresh_external_model_disk_usage", "selected_model_capabilities", "selected_tts_runtime", "set_project_tts_selection", "set_tts_defaults", "tts_catalog", "tts_registry_view",
    "set_tts_active_variant", "write_tts_registry", "verify_tts_asset", "validate_tts_catalog",
])
