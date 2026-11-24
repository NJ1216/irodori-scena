from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from pathlib import Path
from typing import Any

from server.app_deps import HTTPException, keyring
from server.platform_support import require_builtin_llm
from server.registry import deps
from server.modules import llm_registry_io as registry_io
from server.modules.llm_card_defaults import _build_llm_card, _unknown_structured_output
from server.modules.llm_registry_local import invalidate_changed_local_cards
from server.modules.llm_local_fingerprint import _local_fingerprint, _local_root_signature
from server.modules.llm_registry_public import public_llm_registry_impl
from server.modules.llm_registry_deletion import delete_llm_card_impl
from server.modules.llm_registry_resolution import (
    resolve_default_llm_impl,
    resolve_llm_card_impl,
    resolve_llm_settings_impl,
    set_llm_test_status_impl,
)
from server.modules.llm_runtime_binding import LOCK, migrate_bindings, recommended_id, serialized

REGISTRY_FILE = deps.DATA_ROOT / "llm-registry.json"
REGISTRY_VERSION = 5
PROVIDERS = {"ollama", "lmstudio", "openai", "scena-local"}
MEMORY_GUARDS = {"safe", "balanced", "aggressive"}
COMPATIBILITY_SETTINGS = {"contextLimit", "thinking", "trustRemoteCode", "memoryGuard", "mtp"}
SAMPLING_SETTINGS = {"temperature", "topP", "topK", "minP", "repetitionPenalty"}


def _invalidate_changed_local_cards(registry: dict[str, Any]) -> bool:
    return invalidate_changed_local_cards(registry, _local_fingerprint, _local_root_signature)


def _empty_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "defaultCardId": None, "endpoints": [], "cards": []}


def _write_registry(registry: dict[str, Any]) -> None:
    deps.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    registry_io.write_json(REGISTRY_FILE, registry)


@serialized
def write_llm_registry(registry: dict[str, Any]) -> None:
    _write_registry(registry)


# Reads never wait for the runtime lock, which a Windows TTS load holds (see llm_registry_io).
def read_llm_registry() -> dict[str, Any]:
    registry, migrated = _load_llm_registry(persist=False)
    if not migrated:
        return registry
    return registry_io.when_free(LOCK, lambda: _load_llm_registry(persist=True)[0], registry)


def _load_llm_registry(*, persist: bool) -> tuple[dict[str, Any], bool]:
    try:
        value = json.loads(registry_io.read_text(REGISTRY_FILE))
    except (OSError, ValueError, json.JSONDecodeError):
        return _empty_registry(), False
    if not isinstance(value, dict) or value.get("version") not in {1, 2, 3, 4, REGISTRY_VERSION}:
        return _empty_registry(), False
    legacy_capability = value.get("version") in {1, 2}
    migrated = value.get("version") != REGISTRY_VERSION
    value["version"] = REGISTRY_VERSION
    registry = {**_empty_registry(), **value}
    registry["endpoints"] = value.get("endpoints", []) if isinstance(value.get("endpoints"), list) else []
    registry["cards"] = value.get("cards", []) if isinstance(value.get("cards"), list) else []
    for card in registry["cards"]:
        if isinstance(card, dict) and isinstance(card.get("settings"), dict):
            card["settings"].pop("dflash", None)
        if isinstance(card, dict):
            capabilities = dict(card.get("capabilities") or {})
            if legacy_capability or not isinstance(capabilities.get("structuredOutput"), dict):
                capabilities["structuredOutput"] = _unknown_structured_output()
            card["capabilities"] = capabilities
        if isinstance(card, dict):
            metadata = card.get("localMetadata") or {}
            if metadata.get("format") == "GGUF" and metadata.get("modelContextLimit") is None:
                try:
                    from server.modules.llama_cpp_context import model_context_limit

                    context_limit = model_context_limit(metadata)
                except (OSError, ValueError):
                    context_limit = None
                if context_limit is not None:
                    metadata["modelContextLimit"] = context_limit
                    card["localMetadata"] = metadata
                    migrated = True
    endpoint_ids = {item.get("id") for item in registry["endpoints"] if isinstance(item, dict)}
    registry["cards"] = [
        item for item in registry["cards"] if isinstance(item, dict) and item.get("endpointId") in endpoint_ids
    ]
    card_ids = {item.get("id") for item in registry["cards"]}
    if registry["defaultCardId"] not in card_ids:
        registry["defaultCardId"] = None
    if migrated:
        migrate_bindings(registry)
        if persist:
            _write_registry(registry)
    return registry, migrated


def _credential_account(endpoint_id: str) -> str:
    return f"llm-endpoint-{endpoint_id}"


def _has_credential(endpoint_id: str) -> bool:
    return bool(_read_credential(endpoint_id))


def _read_credential(endpoint_id: str) -> str:
    try:
        return keyring.get_password(deps.KEYCHAIN_SERVICE, _credential_account(endpoint_id)) or ""
    except Exception:
        return ""


def public_llm_registry() -> dict[str, Any]:
    version = registry_io.file_version(REGISTRY_FILE)  # an invalidation is saved only when the lock is free
    runtime = SimpleNamespace(
        read=read_llm_registry,
        write=lambda registry: registry_io.when_free(LOCK, lambda: registry_io.save_unless_changed(
            REGISTRY_FILE, version, registry, _write_registry, _invalidate_changed_local_cards, read_llm_registry)),
        invalidate=_invalidate_changed_local_cards,
        has_credential=_has_credential,
    )
    return public_llm_registry_impl(runtime)


def default_llm_card_id() -> str | None:
    value = read_llm_registry().get("defaultCardId")
    return str(value) if value else None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@serialized
def create_llm_endpoint(options: dict[str, Any]) -> dict[str, Any]:
    provider = str(options.get("provider", "")).strip()
    base_url = str(options.get("baseUrl", "")).strip().rstrip("/")
    if provider not in PROVIDERS:
        raise HTTPException(status_code=422, detail="未対応のLLM接続種別です。")
    if provider != "scena-local" and not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="接続先にはHTTPまたはHTTPS URLを指定してください。")
    endpoint = {
        "id": _new_id("endpoint"),
        "provider": provider,
        "displayName": str(options.get("displayName") or provider).strip()[:120],
        "baseUrl": "http://scena.local/v1" if provider == "scena-local" else base_url,
    }
    registry = read_llm_registry()
    registry["endpoints"].append(endpoint)
    _write_registry(registry)
    credential = str(options.get("credential", "")).strip()
    if credential:
        keyring.set_password(deps.KEYCHAIN_SERVICE, _credential_account(endpoint["id"]), credential)
    return {**endpoint, "hasCredential": bool(credential)}


def create_remote_llm_endpoint(options: dict[str, Any]) -> dict[str, Any]:
    if str(options.get("provider", "")).strip() == "scena-local":
        require_builtin_llm()
        raise HTTPException(
            status_code=422, detail="SCENA内蔵モデルはダウンロードまたは外部MLX登録から追加してください。"
        )
    return create_llm_endpoint(options)


def discover_llm_endpoint_models(endpoint_id: str) -> list[str]:
    registry = read_llm_registry()
    endpoint = next((item for item in registry["endpoints"] if item.get("id") == endpoint_id), None)
    if endpoint is None or endpoint.get("provider") == "scena-local":
        raise HTTPException(status_code=404, detail="LLM接続先が見つかりません。")
    credential = _read_credential(endpoint_id)
    request = deps.ModelListRequest(base_url=endpoint["baseUrl"], provider=endpoint["provider"], api_key=credential)
    return deps.list_llm_models(request)


def inspect_remote_llm_models(options: dict[str, Any]) -> list[str]:
    """List models without creating an endpoint or storing its credential."""
    provider = str(options.get("provider", "")).strip()
    base_url = str(options.get("baseUrl", "")).strip().rstrip("/")
    if provider not in PROVIDERS - {"scena-local"}:
        raise HTTPException(status_code=422, detail="未対応のLLM接続種別です。")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="接続先にはHTTPまたはHTTPS URLを指定してください。")
    request = deps.ModelListRequest(
        base_url=base_url, provider=provider, api_key=str(options.get("credential", "")).strip()
    )
    return deps.list_llm_models(request)


@serialized
def create_remote_llm_setting(options: dict[str, Any]) -> dict[str, Any]:
    """Persist one endpoint, model card and optional secret as a single operation."""
    provider = str(options.get("provider", "")).strip()
    model_id = str(options.get("modelId", "")).strip()
    base_url = str(options.get("baseUrl", "")).strip().rstrip("/")
    credential = str(options.get("credential", "")).strip()
    if provider not in PROVIDERS - {"scena-local"}:
        raise HTTPException(status_code=422, detail="未対応のLLM接続種別です。")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="接続先にはHTTPまたはHTTPS URLを指定してください。")
    if not model_id or len(model_id) > 240:
        raise HTTPException(status_code=422, detail="モデルを選択してください。")
    registry = read_llm_registry()
    endpoint = {"id": _new_id("endpoint"), "provider": provider, "displayName": provider, "baseUrl": base_url}
    card = _build_llm_card(endpoint["id"], model_id, options)
    registry["endpoints"].append(endpoint)
    if card["source"] in {"managed", "external"}:
        card["runtimeId"] = recommended_id()
    registry["cards"].append(card)
    registry["defaultCardId"] = card["id"]
    secret_saved = False
    try:
        if credential:
            keyring.set_password(deps.KEYCHAIN_SERVICE, _credential_account(endpoint["id"]), credential)
            secret_saved = True
        _write_registry(registry)
    except Exception:
        if secret_saved:
            try:
                keyring.delete_password(deps.KEYCHAIN_SERVICE, _credential_account(endpoint["id"]))
            except Exception:
                pass
        raise
    return {"registry": public_llm_registry(), "card": card}


def save_llm_endpoint_credential(endpoint_id: str, credential: str) -> dict[str, Any]:
    registry = read_llm_registry()
    endpoint = next((item for item in registry["endpoints"] if item.get("id") == endpoint_id), None)
    if endpoint is None or endpoint.get("provider") == "scena-local":
        raise HTTPException(status_code=404, detail="LLM接続先が見つかりません。")
    value = credential.strip()
    if not value:
        raise HTTPException(status_code=422, detail="API Keyを入力してください。")
    keyring.set_password(deps.KEYCHAIN_SERVICE, _credential_account(endpoint_id), value)
    return {**endpoint, "hasCredential": True}


def delete_llm_endpoint_credential(endpoint_id: str) -> dict[str, Any]:
    registry = read_llm_registry()
    endpoint = next((item for item in registry["endpoints"] if item.get("id") == endpoint_id), None)
    if endpoint is None or endpoint.get("provider") == "scena-local":
        raise HTTPException(status_code=404, detail="LLM接続先が見つかりません。")
    try:
        keyring.delete_password(deps.KEYCHAIN_SERVICE, _credential_account(endpoint_id))
    except Exception:
        pass
    return {**endpoint, "hasCredential": False}


@serialized
def delete_llm_endpoint(endpoint_id: str) -> dict[str, Any]:
    registry = read_llm_registry()
    endpoint = next((item for item in registry["endpoints"] if item.get("id") == endpoint_id), None)
    if endpoint is None:
        raise HTTPException(status_code=404, detail="LLM接続先が見つかりません。")
    if any(item.get("endpointId") == endpoint_id for item in registry["cards"]):
        raise HTTPException(status_code=409, detail="この接続先のLLMモデルを先に登録解除してください。")
    if endpoint.get("provider") == "scena-local":
        raise HTTPException(status_code=422, detail="SCENA内蔵LLMの接続先は削除できません。")
    registry["endpoints"] = [item for item in registry["endpoints"] if item.get("id") != endpoint_id]
    _write_registry(registry)
    try:
        keyring.delete_password(deps.KEYCHAIN_SERVICE, _credential_account(endpoint_id))
    except Exception:
        pass
    return public_llm_registry()


@serialized
def create_llm_card(options: dict[str, Any]) -> dict[str, Any]:
    registry = read_llm_registry()
    endpoint_id = str(options.get("endpointId", ""))
    if not any(item.get("id") == endpoint_id for item in registry["endpoints"]):
        raise HTTPException(status_code=404, detail="LLM接続先が見つかりません。")
    model_id = str(options.get("modelId", "")).strip()
    if not model_id or len(model_id) > 240:
        raise HTTPException(status_code=422, detail="モデルIDを入力してください。")
    card = _build_llm_card(endpoint_id, model_id, options)
    if card["source"] in {"managed", "external"}:
        card["runtimeId"] = recommended_id()
    registry["cards"].append(card)
    if registry["defaultCardId"] is None:
        registry["defaultCardId"] = card["id"]
    _write_registry(registry)
    return card


def create_remote_llm_card(options: dict[str, Any]) -> dict[str, Any]:
    registry = read_llm_registry()
    endpoint_id = str(options.get("endpointId", ""))
    endpoint = next((item for item in registry["endpoints"] if item.get("id") == endpoint_id), None)
    if endpoint is not None and endpoint.get("provider") == "scena-local":
        raise HTTPException(
            status_code=422, detail="SCENA内蔵モデルはダウンロードまたは外部MLX登録から追加してください。"
        )
    return create_llm_card({**options, "source": "remote"})


@serialized
def register_local_llm_card(
    model_id: str, *, source: str, metadata: dict[str, Any], prepare: bool = True
) -> dict[str, Any]:
    if metadata.get("format") == "GGUF" and metadata.get("modelContextLimit") is None:
        try:
            from server.modules.llama_cpp_context import model_context_limit

            metadata = {**metadata, "modelContextLimit": model_context_limit(metadata)}
        except (OSError, ValueError):
            pass
    metadata = {**metadata, "omlxVersion": recommended_id()}
    if path_value := metadata.get("path"):
        path = Path(str(path_value))
        metadata["fingerprint"] = _local_fingerprint(path)
        metadata["rootSignature"] = _local_root_signature(path)
    registry = read_llm_registry()
    endpoint = next((item for item in registry["endpoints"] if item.get("provider") == "scena-local"), None)
    if endpoint is None:
        endpoint = create_llm_endpoint({"provider": "scena-local", "displayName": "SCENA内蔵LLM"})
        registry = read_llm_registry()
    existing = next(
        (
            item
            for item in registry["cards"]
            if item.get("endpointId") == endpoint["id"] and item.get("modelId") == model_id
        ),
        None,
    )
    if existing is not None:
        existing["localMetadata"] = {
            **(existing.get("localMetadata") or {}),
            **metadata,
            "omlxVersion": existing["runtimeId"],
        }
        _write_registry(registry)
        return existing
    card = create_llm_card(
        {
            "endpointId": endpoint["id"],
            "modelId": model_id,
            "displayName": metadata.get("displayName") or model_id,
            "source": source,
            "localMetadata": metadata,
        }
    )
    try:
        from server.modules.model_runtime_jobs import start_model_runtime

        if prepare:
            start_model_runtime(card["id"], automatic=True)
    except HTTPException:
        return card
    registry = read_llm_registry()
    return next((item for item in registry["cards"] if item.get("id") == card["id"]), card)


@serialized
def set_default_llm_card(card_id: str) -> dict[str, Any]:
    registry = read_llm_registry()
    if not any(item.get("id") == card_id for item in registry["cards"]):
        raise HTTPException(status_code=404, detail="LLMモデルが見つかりません。")
    registry["defaultCardId"] = card_id
    _write_registry(registry)
    return public_llm_registry()


@serialized
def update_llm_card(card_id: str, options: dict[str, Any]) -> dict[str, Any]:
    registry = read_llm_registry()
    card = next((item for item in registry["cards"] if item.get("id") == card_id), None)
    if card is None:
        raise HTTPException(status_code=404, detail="LLMモデルが見つかりません。")
    if "displayName" in options:
        display_name = options["displayName"]
        if not isinstance(display_name, str) or not display_name.strip() or len(display_name.strip()) > 160:
            raise HTTPException(status_code=422, detail="表示名を1〜160文字で指定してください。")
        card["displayName"] = display_name.strip()
    settings = dict(card.get("settings") or {})
    updates = options.get("settings")
    if not isinstance(updates, dict):
        raise HTTPException(status_code=422, detail="モデル設定を指定してください。")
    allowed = COMPATIBILITY_SETTINGS | SAMPLING_SETTINGS | {"ttlSeconds"}
    if unknown := set(updates) - allowed:
        raise HTTPException(status_code=422, detail=f"未対応のモデル設定です: {', '.join(sorted(unknown))}")
    context_limit = updates.get("contextLimit", settings.get("contextLimit"))
    if context_limit is not None and (
        isinstance(context_limit, bool)
        or not isinstance(context_limit, int)
        or context_limit < 256
        or context_limit > 1_048_576
    ):
        raise HTTPException(status_code=422, detail="context上限は256〜1048576の整数で指定してください。")
    ttl = updates.get("ttlSeconds", settings.get("ttlSeconds", 300))
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl < 0 or ttl > 86400:
        raise HTTPException(status_code=422, detail="TTLは0〜86400秒の整数で指定してください。")
    guard = updates.get("memoryGuard", settings.get("memoryGuard", "safe"))
    if guard not in MEMORY_GUARDS:
        raise HTTPException(status_code=422, detail="メモリガードはSafe、Balanced、Aggressiveから選択してください。")
    for name in ("thinking", "trustRemoteCode", "mtp"):
        if name in updates and not isinstance(updates[name], bool):
            raise HTTPException(status_code=422, detail=f"{name}は真偽値で指定してください。")
    sampling_ranges = {
        "temperature": (0, 2),
        "topP": (0, 1),
        "topK": (0, 1000),
        "minP": (0, 1),
        "repetitionPenalty": (0, 2),
    }
    for name, (minimum, maximum) in sampling_ranges.items():
        value = updates.get(name, settings.get(name))
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, float)) or value < minimum or value > maximum
        ):
            raise HTTPException(status_code=422, detail=f"{name}は{minimum}〜{maximum}の数値で指定してください。")
    if updates.get("mtp"):
        deps.resolve_mtp_draft(card.get("localMetadata"))
    changed_compatibility = any(
        name in updates and updates[name] != settings.get(name) for name in COMPATIBILITY_SETTINGS
    )
    card["settings"] = {**settings, **updates, "contextLimit": context_limit, "ttlSeconds": ttl, "memoryGuard": guard}
    if changed_compatibility:
        card["testStatus"] = {"state": "untested", "checkedAt": None, "errorCategory": None}
        capabilities = dict(card.get("capabilities") or {})
        capabilities["structuredOutput"] = _unknown_structured_output()
        card["capabilities"] = capabilities
    _write_registry(registry)
    return card


@serialized
def delete_llm_card(card_id: str) -> dict[str, Any]:
    runtime = SimpleNamespace(
        read=read_llm_registry,
        write=_write_registry,
        credential_account=_credential_account,
        public_registry=public_llm_registry,
    )
    return delete_llm_card_impl(card_id, runtime)


def _resolution_runtime() -> SimpleNamespace:
    return SimpleNamespace(read=read_llm_registry, write=_write_registry, read_credential=_read_credential)


def resolve_default_llm() -> dict[str, Any]:
    return resolve_default_llm_impl(_resolution_runtime())


def resolve_llm_card(card_id: str) -> dict[str, Any]:
    return resolve_llm_card_impl(card_id, _resolution_runtime())


def resolve_llm_settings(provider: str, base_url: str, model: str) -> dict[str, Any]:
    return resolve_llm_settings_impl(provider, base_url, model, _resolution_runtime())


@serialized
def set_llm_test_status(card_id: str, status: dict[str, Any]) -> None:
    set_llm_test_status_impl(card_id, status, _resolution_runtime())


deps.register(
    __name__,
    [
        "create_llm_card",
        "create_llm_endpoint",
        "create_remote_llm_card",
        "create_remote_llm_endpoint",
        "create_remote_llm_setting",
        "inspect_remote_llm_models",
        "delete_llm_endpoint",
        "delete_llm_endpoint_credential",
        "discover_llm_endpoint_models",
        "default_llm_card_id",
        "delete_llm_card",
        "public_llm_registry",
        "read_llm_registry",
        "register_local_llm_card",
        "resolve_default_llm",
        "resolve_llm_card",
        "resolve_llm_settings",
        "set_default_llm_card",
        "set_llm_test_status",
        "write_llm_registry",
        "save_llm_endpoint_credential",
        "update_llm_card",
    ],
)
