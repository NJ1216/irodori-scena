from __future__ import annotations

import importlib

from server import application
from server.app_deps import http as http
from server.registry import deps

_MODULE_PATHS = [
    "server.modules.constants",
    "server.modules.project_container",
    "server.modules.project_cache_storage",
    "server.modules.request_model",
    "server.modules.models",
    "server.modules.line_split",
    "server.modules.project_models",
    "server.modules.script_assistant_models",
    "server.modules.export_models",
    "server.modules.public_llm_models",
    "server.modules.llm_registry",
    "server.modules.llm_registry_metadata",
    "server.modules.tts_registry",
    "server.modules.tts_libraries",
    "server.modules.tts_downloads",
    "server.modules.huggingface_models",
    "server.modules.huggingface_gguf",
    "server.modules.mtp_assets",
    "server.modules.runtime_state",
    "server.modules.llm_session_usage",
    "server.modules.progress_events",
    "server.modules.job_retention",
    "server.modules.local_llm_storage",
    "server.modules.llama_cpp_context",
    "server.modules.llama_cpp_models",
    "server.modules.llama_cpp_runtime",
    "server.modules.llama_cpp_server",
    "server.modules.resource_coordinator",
    "server.modules.memory_metrics",
    "server.modules.omlx_environment",
    "server.modules.omlx_environment_routes",
    "server.modules.local_llm_runtime",
    "server.modules.local_llm_metrics",
    "server.modules.common",
    "server.modules.dialogue_cues",
    "server.modules.cue_mix",
    "server.modules.overlap_mix",
    "server.modules.workspace",
    "server.modules.connection_settings",
    "server.modules.project_repository",
    "server.modules.derived_audio_preparation",
    "server.modules.derived_audio_routes",
    "server.modules.timeline_routes",
    "server.modules.project_backup_service",
    "server.modules.project_patch_service",
    "server.modules.take_integrity",
    "server.modules.take_cleanup",
    "server.modules.media_integrity",
    "server.modules.project_cache_cleanup",
    "server.modules.history",
    "server.modules.character_profiles",
    "server.modules.draft_cast_context",
    "server.modules.draft_cast_phases",
    "server.modules.cast_sync",
    "server.modules.pronunciation_suggestions",
    "server.modules.pronunciation_dictionary",
    "server.modules.line_pronunciations",
    "server.modules.project_pronunciation_snapshot",
    "server.modules.inference",
    "server.modules.tts_runtime",
    "server.modules.tts_cuda_warmup",
    "server.modules.worker_priority",
    "server.modules.lora_assets",
    "server.modules.voice_reference",
    "server.modules.llm_emoji_policy",
    "server.modules.draft_validation",
    "server.modules.llm_voice_design_parser",
    "server.modules.relation_address_policy",
    "server.modules.profile_relation_resolver",
    "server.modules.llm_response_formatters",
    "server.modules.llm_profile_formatter",
    "server.modules.llm_sampling",
    "server.modules.llm_prompt_profile",
    "server.modules.llm_contracts",
    "server.modules.llm_transport",
    "server.modules.lmstudio_native",
    "server.modules.ollama_native",
    "server.modules.llm_stream_transport",
    "server.modules.llm_client",
    "server.modules.llm_completion_service",
    "server.modules.cast_context_cache",
    "server.modules.draft_plan_contracts",
    "server.modules.assistant_contracts",
    "server.modules.llm_model_tests",
    "server.modules.direction_optimization",
    "server.modules.draft_token_planning",
    "server.modules.draft_capability",
    "server.modules.direction_context",
    "server.modules.ai_direction_prompt",
    "server.modules.direction_fields",
    "server.modules.draft_theme",
    "server.modules.draft_outline_fallback",
    "server.modules.draft_planning",
    "server.modules.draft_packets",
    "server.modules.draft_continuity",
    "server.modules.draft_dialogue",
    "server.modules.draft_performance",
    "server.modules.ai_direction",
    "server.modules.suggestions",
    "server.modules.profile_suggestions",
    "server.modules.image_prompt_suggestions",
    "server.modules.project_routes",
    "server.modules.project_patch_routes",
    "server.modules.tts_registry_routes",
    "server.modules.lora_routes",
    "server.modules.lora_preview",
    "server.modules.rhubarb_runtime",
    "server.modules.rhubarb_lipsync",
    "server.modules.llm_registry_routes",
    "server.modules.llm_session_routes",
    "server.modules.local_llm_routes",
    "server.modules.assistant_routes",
    "server.modules.script_assistant_context",
    "server.modules.script_assistant_fitting",
    "server.modules.script_assistant_summary",
    "server.modules.script_assistant_apply",
    "server.modules.script_assistant_jobs",
    "server.modules.script_assistant_routes",
    "server.modules.profile_suggestion_routes",
    "server.modules.character_routes",
    "server.modules.character_avatar_routes",
    "server.modules.cast_exchange",
    "server.modules.candidate_clear_routes",
    "server.modules.pronunciation_routes",
    "server.modules.take_commit",
    "server.modules.script_routes",
    "server.modules.draft_algorithms",
    "server.modules.draft_forward",
    "server.modules.draft_notation",
    "server.modules.draft_repair",
    "server.modules.export_service",
    "server.modules.export_bundle",
    "server.modules.draft_job_state",
    "server.modules.draft_stream_progress",
    "server.modules.draft_schedule",
    "server.modules.draft_forward_job",
    "server.modules.draft_jobs",
    "server.modules.job_routes",
]
_MODULES = [importlib.import_module(path) for path in _MODULE_PATHS]

# Preserve the original import-time workspace restoration before media routes.
deps.restore_active_workspace()
deps.ensure_data_root()
deps.discard_restored_voice_candidates()
deps.migrate_legacy_scratch_characters()
_MODULES.append(importlib.import_module("server.modules.media_routes"))


def create_app(*, dependency_overrides=None):
    """Return the fully registered default application.

    Tests may supply FastAPI dependency overrides without changing normal
    startup, which remains ``server.app:app``.
    """
    if dependency_overrides:
        application.app.dependency_overrides.update(dependency_overrides)
    return application.app


app = create_app()
for _name in deps.names():
    globals()[_name] = getattr(deps, _name)

__all__ = ["app", "create_app", *deps.names()]
