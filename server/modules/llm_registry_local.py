from __future__ import annotations

from pathlib import Path
from typing import Any
from server.modules.llm_card_defaults import _unknown_structured_output
from server.modules.llm_local_fingerprint import _local_fingerprint, _local_root_signature


def invalidate_changed_local_cards(
    registry: dict[str, Any], fingerprint=_local_fingerprint, root_signature_for=_local_root_signature
) -> bool:
    changed = False
    for card in registry["cards"]:
        if card.get("source") not in {"managed", "external"}:
            continue
        version = card.get("runtimeId")
        metadata = card.get("localMetadata") or {}
        path = Path(str(metadata.get("path", "")))
        root_signature = root_signature_for(path)
        signature_changed = root_signature != metadata.get("rootSignature")
        current = fingerprint(path) if signature_changed else metadata.get("fingerprint")
        stale = current != metadata.get("fingerprint") or version != metadata.get("omlxVersion")
        if current and metadata.get("fingerprint") is None:
            stale = False
        if stale and card.get("testStatus", {}).get("state") != "untested":
            card["testStatus"] = {"state": "untested", "checkedAt": None, "errorCategory": None}
            capabilities = dict(card.get("capabilities") or {})
            capabilities["structuredOutput"] = _unknown_structured_output()
            card["capabilities"] = capabilities
            changed = True
        if signature_changed or current != metadata.get("fingerprint") or version != metadata.get("omlxVersion"):
            metadata.update(fingerprint=current, rootSignature=root_signature, omlxVersion=version)
            card["localMetadata"] = metadata
            changed = True
    return changed
