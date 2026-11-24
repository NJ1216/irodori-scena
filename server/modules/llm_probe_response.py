"""Bounded probe options and diagnostic parsing; never retries a probe."""
from typing import Any

from server.modules.llm_gemini_options import gemini_reasoning_options, gemini_thinking_model


class ProbeResponseError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


def probe_options(selected: dict[str, Any], default_tokens: int) -> dict[str, Any]:
    if gemini_thinking_model(selected["provider"], selected["model"]):
        # Gemini thinking shares the generation budget with the visible answer.
        # https://ai.google.dev/gemini-api/docs/openai#thinking
        return {"max_tokens": 4096, **gemini_reasoning_options(selected["provider"], selected["model"])}
    return {"max_tokens": default_tokens}


def probe_completion_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ProbeResponseError("invalid_response", "OpenAI chat completion形式の応答を確認できませんでした。")
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProbeResponseError("invalid_response", "OpenAI chat completion形式のmessageを確認できませんでした。")
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if choice.get("finish_reason") == "length":
        raise ProbeResponseError("output_limit", "動作確認の出力上限に達し、本文が返りませんでした。OpenAI互換性の問題とは限りません。")
    if choice.get("finish_reason") == "content_filter" or message.get("refusal"):
        raise ProbeResponseError("response_blocked", "モデル側で動作確認への応答が拒否されました。")
    raise ProbeResponseError("empty_response", "応答形式は確認できましたが、本文が空でした。")
