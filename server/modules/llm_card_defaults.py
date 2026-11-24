from __future__ import annotations

import uuid
from typing import Any

def _unknown_structured_output() -> dict[str, Any]:
    item = {"state": "unknown", "reasonCode": None}
    return {"nonStreaming": dict(item), "streaming": dict(item), "checkedAt": None}

def _build_llm_card(endpoint_id: str, model_id: str, options: dict[str, Any]) -> dict[str, Any]:
    return {"id": f"card_{uuid.uuid4().hex[:16]}", "endpointId": endpoint_id, "modelId": model_id,
            "displayName": str(options.get("displayName") or model_id).strip()[:160],
            "source": str(options.get("source") or "remote"), "localMetadata": options.get("localMetadata"),
            "settings": {"contextLimit": None, "thinking": False, "ttlSeconds": 300,
                         "trustRemoteCode": False, "memoryGuard": "safe", "temperature": None,
                         "topP": None, "topK": None, "minP": None, "repetitionPenalty": None,
                         **(options.get("settings") or {})},
            "capabilities": {**(options.get("capabilities") or {}),
                             "structuredOutput": _unknown_structured_output()}, "lastProbe": None,
            "testStatus": {"state": "untested", "checkedAt": None, "errorCategory": None},
            "usageHistory": []}

