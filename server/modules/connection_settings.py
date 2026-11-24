"""Connection settings and API-key storage in the OS credential store."""

from __future__ import annotations

from server.app_deps import hashlib, json, sys, Path, Any, HTTPException, keyring
from server.registry import deps

_CREDENTIAL_STORE = "OSの資格情報ストア" if sys.platform == "win32" else "macOS Keychain"


def default_connection_settings() -> dict[str, Any]:
    return {
        "provider": "ollama",
        "baseUrl": "http://127.0.0.1:11434/v1",
        "model": "",
        "apiKeyEnabled": False,
        "hasApiKey": False,
        "engineDir": "",
        "engineDirVerified": False,
    }


def connection_keychain_account(settings: dict[str, Any]) -> str:
    """Return a stable, non-descriptive account id for one endpoint."""
    provider = str(settings.get("provider", "")).strip()
    base_url = str(settings.get("baseUrl", "")).strip().rstrip("/").lower()
    digest = hashlib.sha256(f"{provider}\n{base_url}".encode("utf-8")).hexdigest()
    return f"endpoint-{digest}"


def read_connection_api_key(settings: dict[str, Any] | None = None) -> str:
    """Read the active endpoint's key from macOS Keychain, never from disk."""
    try:
        return str(deps.resolve_default_llm()["apiKey"])
    except HTTPException:
        pass
    active = settings or read_connection_settings()
    if not bool(active.get("apiKeyEnabled", False)):
        return ""
    try:
        return keyring.get_password(deps.KEYCHAIN_SERVICE, connection_keychain_account(active)) or ""
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"{_CREDENTIAL_STORE} にアクセスできませんでした: {error}") from error


def store_connection_api_key(settings: dict[str, Any], api_key: str) -> None:
    try:
        keyring.set_password(deps.KEYCHAIN_SERVICE, connection_keychain_account(settings), api_key)
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=f"{_CREDENTIAL_STORE} にAPI Keyを保存できませんでした: {error}"
        ) from error


def delete_connection_api_key(settings: dict[str, Any]) -> None:
    try:
        keyring.delete_password(deps.KEYCHAIN_SERVICE, connection_keychain_account(settings))
    except keyring.errors.PasswordDeleteError:
        pass
    except Exception as error:
        raise HTTPException(
            status_code=500, detail=f"{_CREDENTIAL_STORE} からAPI Keyを削除できませんでした: {error}"
        ) from error


def read_connection_settings() -> dict[str, Any]:
    defaults = default_connection_settings()
    loaded: dict[str, Any] = {}
    try:
        loaded = json.loads(deps.CONNECTION_SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    if not isinstance(loaded, dict):
        loaded = {}
    try:
        selected = deps.resolve_default_llm()
    except HTTPException:
        selected = None
    provider = str(selected["provider"] if selected else defaults["provider"])
    settings = {
        "provider": provider if provider in {"ollama", "lmstudio", "openai", "scena-local"} else defaults["provider"],
        "baseUrl": str(selected["baseUrl"] if selected else defaults["baseUrl"]),
        "model": str(selected["model"] if selected else ""),
        "apiKeyEnabled": bool(selected and selected["apiKey"]),
        "engineDir": str(loaded.get("engineDir", "")).strip(),
    }
    if settings["apiKeyEnabled"]:
        try:
            settings["hasApiKey"] = bool(
                keyring.get_password(deps.KEYCHAIN_SERVICE, connection_keychain_account(settings))
            )
        except Exception:
            settings["hasApiKey"] = False
    else:
        settings["hasApiKey"] = False
    settings["engineDirVerified"] = bool(
        settings["engineDir"] and (Path(settings["engineDir"]).expanduser() / "infer.py").is_file()
    )
    return settings


def write_connection_settings(settings: deps.ConnectionSettingsRequest) -> dict[str, Any]:
    deps.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    previous = read_connection_settings()
    saved = {
        "provider": settings.provider,
        "baseUrl": settings.base_url.strip(),
        "model": settings.model.strip(),
        "apiKeyEnabled": settings.api_key_enabled,
        "engineDir": settings.engine_dir.strip(),
    }
    if not saved["apiKeyEnabled"]:
        delete_connection_api_key(previous)
        delete_connection_api_key(saved)
    elif settings.api_key is not None and settings.api_key.strip():
        store_connection_api_key(saved, settings.api_key.strip())
        if connection_keychain_account(previous) != connection_keychain_account(saved):
            delete_connection_api_key(previous)
    temporary = deps.CONNECTION_SETTINGS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(deps.CONNECTION_SETTINGS_FILE)
    saved["hasApiKey"] = bool(read_connection_api_key(saved)) if saved["apiKeyEnabled"] else False
    saved["engineDirVerified"] = bool(
        saved["engineDir"] and (Path(saved["engineDir"]).expanduser() / "infer.py").is_file()
    )
    return saved


def write_engine_directory(engine_dir: str) -> dict[str, str]:
    deps.DATA_ROOT.mkdir(parents=True, exist_ok=True)
    saved = {"engineDir": engine_dir.strip()}
    temporary = deps.CONNECTION_SETTINGS_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(deps.CONNECTION_SETTINGS_FILE)
    return saved


deps.register(
    __name__,
    [
        "default_connection_settings",
        "connection_keychain_account",
        "read_connection_api_key",
        "store_connection_api_key",
        "delete_connection_api_key",
        "read_connection_settings",
        "write_connection_settings",
        "write_engine_directory",
    ],
)
