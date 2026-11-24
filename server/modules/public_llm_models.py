"""Frontend AI request contracts resolved through the default LLM card."""

from pydantic import ConfigDict, create_model, model_validator

from server.app_deps import BaseModel
from server.registry import deps

_TRANSPORT_FIELDS = {"base_url", "model", "api_key", "provider"}


def _public_request(name: str, internal: type[BaseModel]) -> type[BaseModel]:
    def validate_internal(self: BaseModel) -> BaseModel:
        # Copying fields alone loses model validators (including mode-specific
        # draft constraints). Validate at the HTTP boundary, not inside a route
        # where ValidationError becomes a CORS-inaccessible 500 response.
        internal.model_validate(self.model_dump())
        return self

    fields = {
        field_name: (field.annotation, field)
        for field_name, field in internal.model_fields.items()
        if field_name not in _TRANSPORT_FIELDS
    }
    return create_model(name, __config__=ConfigDict(extra="forbid"),
                        __validators__={"validate_internal": model_validator(mode="after")(validate_internal)}, **fields)


AiJobApiRequest = _public_request("AiJobApiRequest", deps.AiJobRequest)
DraftApiRequest = _public_request("DraftApiRequest", deps.DraftRequest)
LineAssistantApiRequest = _public_request("LineAssistantApiRequest", deps.LineAssistantRequest)
ScriptAssistantApiRequest = _public_request("ScriptAssistantApiRequest", deps.ScriptAssistantRequest)
ThemeSuggestionApiRequest = _public_request("ThemeSuggestionApiRequest", deps.ThemeSuggestionRequest)
VoiceDesignSuggestionApiRequest = _public_request("VoiceDesignSuggestionApiRequest", deps.VoiceDesignSuggestionRequest)
CharacterProfileSuggestionApiRequest = _public_request(
    "CharacterProfileSuggestionApiRequest", deps.CharacterProfileSuggestionRequest
)
ImagePromptSuggestionApiRequest = _public_request("ImagePromptSuggestionApiRequest", deps.ImagePromptSuggestionRequest)

deps.register(__name__, [
    "AiJobApiRequest", "DraftApiRequest", "LineAssistantApiRequest", "ScriptAssistantApiRequest", "ThemeSuggestionApiRequest",
    "VoiceDesignSuggestionApiRequest", "CharacterProfileSuggestionApiRequest", "ImagePromptSuggestionApiRequest",
])
