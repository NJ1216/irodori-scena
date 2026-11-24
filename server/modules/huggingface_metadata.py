from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from huggingface_hub import HfApi
from huggingface_hub.errors import GatedRepoError, HfHubHTTPError, RepositoryNotFoundError

from server.registry import deps
from server.modules.huggingface_model_size import model_download_size, size_format
from server.modules.huggingface_gguf_catalog import catalog_from_info

METADATA_CACHE_MAX_AGE_SECONDS = 180 * 24 * 60 * 60
_CACHE_LOCK = threading.RLock()
_PARAMETER = re.compile(r"(?i)^(\d+(?:\.\d+)?)([bt])$")
_BIT_QUANTIZATION = re.compile(r"^\d+bit$")
_QUANTIZATION = {"mxfp4": "MXFP4", "nvfp4": "NVFP4", "fp4": "FP4", "bf16": "BF16", "fp16": "FP16", "int4": "INT4", "int8": "INT8", "q4": "Q4", "q8": "Q8", "4bit": "4bit", "8bit": "8bit", "qat": "QAT", "gguf": "GGUF", "awq": "AWQ", "gptq": "GPTQ"}
_PURPOSES = {"it": "Instruct", "instruct": "Instruct", "instruction": "Instruct", "chat": "Chat", "base": "Base", "coder": "Coder", "code": "Coder", "vision": "Vision", "vl": "Vision", "distill": "Distilled", "distilled": "Distilled", "thinking": "Thinking", "reasoning": "Thinking", "safeguard": "Safety"}
_ROLES = {"assistant": "Assistant", "drafter": "Drafter"}
_FAMILY_CASE = {"gemma": "Gemma", "qwen": "Qwen", "llama": "Llama", "deepseek": "DeepSeek"}
_PLATFORM_MARKERS = {"mlx"}


def _tokens(name: str) -> list[str]:
    value = re.sub(r"[_\s-]+", " ", name.strip()).casefold()
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?|[^\W\d_]+", value)


def _canonical_family(tokens: list[str]) -> str:
    for marker in ("gemma", "qwen", "llama", "deepseek"):
        if marker not in tokens:
            continue
        index = tokens.index(marker)
        tail = tokens[index:index + 3]
        if marker == "deepseek" and len(tail) >= 3 and tail[1] == "r" and tail[2].isdigit():
            return f"DeepSeek R{tail[2]}"
        if len(tail) >= 2 and tail[1].replace(".", "").isdigit():
            return f"{_FAMILY_CASE[marker]} {tail[1]}"
        return _FAMILY_CASE[marker]
    for index in range(len(tokens) - 1):
        if tokens[index:index + 2] == ["gpt", "oss"]:
            return "gpt-oss"
    return ""


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def inferred_tags(repo_name: str) -> list[dict[str, str]]:
    tokens = _tokens(repo_name)
    parameter: str | None = None
    quantizations: list[str] = []
    purposes: list[str] = []
    roles: list[str] = []
    platforms = [marker.upper() for marker in _PLATFORM_MARKERS.intersection(tokens)]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in _PLATFORM_MARKERS:
            index += 1
            continue
        if (token == "a" and index + 2 < len(tokens) and tokens[index + 1].replace(".", "").isdigit()
                and tokens[index + 2] in {"b", "t"}):
            index += 3
            continue
        if token == "e" and index + 2 < len(tokens) and tokens[index + 1].replace(".", "").isdigit() \
                and tokens[index + 2] == "b":
            parameter = parameter or f"E{tokens[index + 1]}B"
            index += 3
            continue
        if token == "oq" and index + 2 < len(tokens) and tokens[index + 1].replace(".", "").isdigit() \
                and tokens[index + 2] == "e":
            _append_unique(quantizations, f"oQ{tokens[index + 1]}e")
            index += 3
            continue
        if token in {"optiq", "axq"}:
            _append_unique(quantizations, {"optiq": "OptiQ", "axq": "AXQ"}[token])
            index += 1
            continue
        combined = token
        quantization_token = token
        if index + 1 < len(tokens) and (token + tokens[index + 1] in _QUANTIZATION or
                                        _BIT_QUANTIZATION.fullmatch(token + tokens[index + 1])):
            quantization_token = token + tokens[index + 1]
            index += 1
        if token.replace(".", "").isdigit() and index + 1 < len(tokens) and tokens[index + 1] in {"b", "t"}:
            combined = token + tokens[index + 1]
            index += 1
        if match := _PARAMETER.fullmatch(combined):
            parameter = parameter or f"{match.group(1)}{match.group(2).upper()}"
        elif quantization_token in _QUANTIZATION or _BIT_QUANTIZATION.fullmatch(quantization_token):
            quantization = _QUANTIZATION.get(quantization_token, quantization_token)
            _append_unique(quantizations, quantization)
        elif token in _PURPOSES:
            _append_unique(purposes, _PURPOSES[token])
        elif token in _ROLES:
            _append_unique(roles, _ROLES[token])
        index += 1
    family = _canonical_family(tokens)
    # Repository names are free-form. Unknown prefixes are commonly publishers,
    # training recipes, or branding, so they are not safe family facets.
    tags = ([{"kind": "family", "value": family}] if family else [])
    if parameter:
        tags.append({"kind": "parameters", "value": parameter})
    tags.extend({"kind": "quantization", "value": value} for value in quantizations)
    tags.extend({"kind": "purpose", "value": value} for value in purposes)
    tags.extend({"kind": "role", "value": value} for value in roles)
    tags.extend({"kind": "compatibility", "value": value} for value in platforms)
    return tags


def infer_local_model_tags(path: Path) -> list[dict[str, str]]:
    try:
        config = json.loads((path / "config.json").read_text(encoding="utf-8"))
        config = config if isinstance(config, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        config = {}
    generic_names = {"model", "models", "mlx", "weights", "checkpoint"}
    sources = [] if path.name.casefold() in generic_names else [path.name]
    configured_name = str(config.get("_name_or_path") or "").rstrip("/").split("/")[-1]
    if configured_name:
        sources.append(configured_name)
    model_type = str(config.get("model_type") or "")
    if model_type:
        sources.append(model_type)
    if not sources:
        for candidate in sorted(path.glob("*.safetensors")):
            stem = re.sub(r"-\d+-of-\d+$", "", candidate.stem, flags=re.IGNORECASE)
            if stem.casefold() not in generic_names:
                sources.append(stem)
                break
    inferred = [inferred_tags(source) for source in sources]
    tags: list[dict[str, str]] = []
    for kind in ("family", "parameters", "quantization", "purpose", "role", "compatibility"):
        for group in inferred:
            for tag in group:
                if tag["kind"] == kind and tag not in tags:
                    tags.append(tag)
            if kind == "family" and any(tag["kind"] == kind for tag in tags):
                break
    quant = config.get("quantization") or config.get("quantization_config") or {}
    if isinstance(quant, dict):
        raw_quantization = str(quant.get("bits") or quant.get("quant_method") or "")
    else:
        raw_quantization = str(quant or "")
    if raw_quantization:
        value = f"{raw_quantization}bit" if raw_quantization.isdigit() else raw_quantization.upper()
        tags = [tag for tag in tags if tag["kind"] != "quantization"]
        tags.append({"kind": "quantization", "value": value})
    order = {"family": 0, "parameters": 1, "quantization": 2, "purpose": 3, "role": 4, "compatibility": 5}
    return sorted(tags, key=lambda tag: order[tag["kind"]])


def _cache_path() -> Path:
    return deps.DATA_ROOT / "huggingface-model-metadata-cache.json"


def _load_cache() -> dict[str, dict[str, Any]]:
    try:
        entries = json.loads(_cache_path().read_text(encoding="utf-8")).get("repositories", {})
        return entries if isinstance(entries, dict) else {}
    except (OSError, TypeError, json.JSONDecodeError):
        return {}


def _write_cache(entries: dict[str, dict[str, Any]]) -> None:
    cutoff = time.time() - METADATA_CACHE_MAX_AGE_SECONDS
    kept = {key: value for key, value in entries.items() if float(value.get("lastAccessedAt", 0)) >= cutoff}
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"version": 1, "repositories": kept}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def cached_size(repo_id: str, revision: str) -> int | None:
    with _CACHE_LOCK:
        entry = _load_cache().get(repo_id)
    return entry["downloadSizeBytes"] if _valid_size(entry, revision) else None


def _valid_size(entry, revision):
    return bool(entry and entry.get("revision") == revision and entry.get("sizeFormat") == size_format()
                and isinstance(entry.get("downloadSizeBytes"), int))


def cached_gguf_catalog(repo_id, revision):
    with _CACHE_LOCK:
        entry = _load_cache().get(repo_id)
    if entry and entry.get("revision") == revision and entry.get("sizeFormat") == "gguf-v3":
        return entry.get("ggufVariants")
    return None


def fetch_metadata_sizes(items: list[dict[str, str]], token_provider: Callable[[], str | None]) -> dict[str, Any]:
    if not 1 <= len(items) <= 30:
        raise ValueError("repositories must contain 1 to 30 items")
    requested = {str(item.get("repoId", "")): str(item.get("revision", "")) for item in items}
    if any(not repo or not revision for repo, revision in requested.items()) or len(requested) != len(items):
        raise ValueError("repoId and revision must be non-empty and unique")
    now = time.time()
    with _CACHE_LOCK:
        entries = _load_cache()
    results: dict[str, int | None] = {}
    catalogs = {}
    missing: list[tuple[str, str]] = []
    for repo, revision in requested.items():
        entry = entries.get(repo)
        if _valid_size(entry, revision):
            entry["lastAccessedAt"] = now
            results[repo] = entry["downloadSizeBytes"]
            if "ggufVariants" in entry:
                catalogs[repo] = entry["ggufVariants"]
        else:
            missing.append((repo, revision))

    def fetch(repo: str, revision: str):
        api = HfApi(token=False)
        try:
            info = api.model_info(repo, revision=revision, files_metadata=True, token=False)
        except (GatedRepoError, RepositoryNotFoundError):
            token = token_provider()
            if not token:
                return repo, revision, None, None
            try:
                info = api.model_info(repo, revision=revision, files_metadata=True, token=token)
            except HfHubHTTPError:
                return repo, revision, None, None
        except HfHubHTTPError:
            return repo, revision, None, None
        return repo, revision, model_download_size(info), catalog_from_info(info) if size_format() == "gguf-v3" else None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch, repo, revision) for repo, revision in missing]
        for future in as_completed(futures):
            repo, revision, size, catalog = future.result()
            results[repo] = size
            if catalog is not None:
                catalogs[repo] = catalog
            if size is not None or catalog is not None:
                entries[repo] = {"revision": revision, "downloadSizeBytes": size, "lastAccessedAt": now, "sizeFormat": size_format()}
                if catalog is not None:
                    entries[repo]["ggufVariants"] = catalog
    with _CACHE_LOCK:
        _write_cache(entries)
    return {"models": [{"repoId": repo, "downloadSizeBytes": results.get(repo),
                        **({"ggufVariants": catalogs[repo]} if repo in catalogs else {})} for repo in requested]}
