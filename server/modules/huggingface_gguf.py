from __future__ import annotations

import re
from typing import Any

from huggingface_hub import HfApi

from server.registry import deps

QUANTIZATION = re.compile(r"(?:^|[._-])((?:UD-)?(?:IQ\d_(?:XXS|XS|S|M|NL)|Q\d_K(?:_(?:XL|S|M|L))?|Q\d_[0-3](?:_\d+)*|TQ\d_\d+|Q\d|MXFP4|NVFP4|BF16|FP16|FP32|F16|F32))(?=$|[.-])", re.IGNORECASE)


def quantization_label(name: str) -> str | None:
    matches = list(QUANTIZATION.finditer(name.rsplit("/", 1)[-1]))
    return matches[-1].group(1).upper() if matches else None


def gguf_compatibility(model: Any) -> tuple[str, str | None]:
    tags = {str(tag).lower() for tag in (getattr(model, "tags", None) or [])}
    siblings = getattr(model, "siblings", None) or []
    if "gguf" in tags or any(str(getattr(item, "rfilename", "")).lower().endswith(".gguf") for item in siblings):
        return "gguf", None
    return "incompatible", "GGUF形式ではありません。"


def variants_from_info(repo_id: str, info: Any) -> dict[str, Any]:
    groups: dict[str, list[Any]] = {}
    shard_pattern = re.compile(r"^(.*?)-(\d{5})-of-(\d{5})\.gguf$", re.IGNORECASE)
    for item in info.siblings or []:
        name = str(item.rfilename or "")
        if name.lower().endswith(".gguf") and not re.search(r"(?:^|[._-])mmproj(?:[._-]|$)", name.rsplit("/", 1)[-1], re.IGNORECASE):
            match = shard_pattern.match(name)
            groups.setdefault(match.group(1) if match else name[:-5], []).append(item)
    variants = []
    for name, files in groups.items():
        files.sort(key=lambda item: str(item.rfilename))
        match = shard_pattern.match(str(files[0].rfilename))
        expected = int(match.group(3)) if match else 1
        indexes = [shard_pattern.match(str(item.rfilename)) for item in files]
        complete = not match or all(item and int(item.group(3)) == expected for item in indexes) and {int(item.group(2)) for item in indexes if item} == set(range(1, expected + 1))
        if len(files) == expected and complete:
            variants.append({"id": name, "quantization": quantization_label(name) or name.rsplit("/", 1)[-1],
                             "files": [item.rfilename for item in files], "shardCount": len(files),
                             "downloadSizeBytes": sum(item.size for item in files) if all(isinstance(getattr(item, "size", None), int) and item.size > 0 for item in files) else 0})
    return {"repoId": repo_id, "revision": str(getattr(info, "sha", "") or ""), "variants": variants}


def gguf_variants(repo_id: str) -> dict[str, Any]:
    from server.modules.huggingface_models import _model_info_with_optional_token
    info, _token_value = _model_info_with_optional_token(HfApi(token=False), repo_id, files_metadata=True)
    return variants_from_info(repo_id, info)


deps.register(__name__, ["gguf_compatibility", "gguf_variants", "variants_from_info"])
