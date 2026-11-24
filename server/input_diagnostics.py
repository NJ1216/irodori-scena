"""Development-only validation diagnostics without submitted content or secrets."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError

from server.registry import deps

LOGGER = logging.getLogger("uvicorn.error")
CONSTRAINTS = {
    "draft speech_rate must be numeric": "draft_speech_rate_numeric",
    "performance_speech_rate_min must not exceed performance_speech_rate_max": "speech_rate_range_order",
    "performance_gap_min must not exceed performance_gap_max": "gap_range_order",
    "minimum must not exceed maximum": "range_order",
    "allowed_emojis contains unsupported emoji:": "unsupported_emoji",
}


def safe_validation_issues(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fields = {"body", *deps.AiJobRequest.model_fields, *deps.DraftCastSettings.model_fields}
    result = []
    for error in errors[:20]:
        location = [part if isinstance(part, int) or part in fields else "<field>"
                    for part in error.get("loc", ())]
        issue = {"field": location, "type": error.get("type", "unknown")}
        message = str(error.get("msg", "")).removeprefix("Value error, ")
        for prefix, code in CONSTRAINTS.items():
            if message.startswith(prefix):
                issue["constraint"] = code
                break
        result.append(issue)
    return result


def install_input_diagnostics(application: FastAPI) -> None:
    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if request.url.path == "/api/ai/jobs":
            LOGGER.warning("[SCENA input rejected] POST /api/ai/jobs: %s", safe_validation_issues(error.errors()))
        return await request_validation_exception_handler(request, error)
