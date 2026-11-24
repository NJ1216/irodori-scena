from __future__ import annotations

from server.app_deps import subprocess, threading, Any
from server.registry import deps

DRAFT_JOBS: dict[str, dict[str, Any]] = {}

DRAFT_JOBS_LOCK = threading.RLock()

DRAFT_LLM_RESPONSES: dict[str, Any] = {}

DRAFT_LLM_RESPONSES_LOCK = threading.RLock()

PRONUNCIATION_LLM_LOCK = threading.RLock()

DRAFT_LLM_THREAD_CONTEXT = threading.local()

DRAFT_YIELD_PROFILES_LOCK = threading.RLock()

EXPORT_JOBS: dict[str, dict[str, Any]] = {}

EXPORT_JOBS_LOCK = threading.RLock()

INFERENCE_WORKER_LOCK = threading.RLock()

INFERENCE_WORKER: subprocess.Popen[str] | None = None

AUTO_RENDER_INTERRUPT = threading.Event()
AUTO_RENDER_INTERRUPT_LOCK = threading.RLock()
AUTO_RENDER_ACTIVE: dict[str, str | None] = {"lineId": None}

VOICE_CANDIDATE_GENERATION_LOCK = threading.RLock()

VOICE_CANDIDATE_GENERATION_EPOCH = 0

PROFILE_SUGGESTION_JOBS: dict[str, dict[str, Any]] = {}

PROFILE_SUGGESTION_JOBS_LOCK = threading.RLock()

SCRIPT_ASSISTANT_JOBS: dict[str, dict[str, Any]] = {}

SCRIPT_ASSISTANT_JOBS_LOCK = threading.RLock()

SCRIPT_ASSISTANT_PROPOSALS: dict[str, dict[str, Any]] = {}

SCRIPT_ASSISTANT_SUMMARY_CACHE: dict[tuple[str, str, str, str, str], str] = {}

SCRIPT_ASSISTANT_SUMMARY_CACHE_LOCK = threading.RLock()

WORKER_RESULT_PREFIX = "__SCENA_RESULT__"

deps.register(
    __name__,
    [
        "DRAFT_JOBS",
        "DRAFT_JOBS_LOCK",
        "DRAFT_LLM_RESPONSES",
        "DRAFT_LLM_RESPONSES_LOCK",
        "PRONUNCIATION_LLM_LOCK",
        "DRAFT_LLM_THREAD_CONTEXT",
        "DRAFT_YIELD_PROFILES_LOCK",
        "EXPORT_JOBS",
        "EXPORT_JOBS_LOCK",
        "INFERENCE_WORKER",
        "INFERENCE_WORKER_LOCK",
        "AUTO_RENDER_INTERRUPT",
        "AUTO_RENDER_INTERRUPT_LOCK",
        "AUTO_RENDER_ACTIVE",
        "VOICE_CANDIDATE_GENERATION_EPOCH",
        "VOICE_CANDIDATE_GENERATION_LOCK",
        "PROFILE_SUGGESTION_JOBS",
        "PROFILE_SUGGESTION_JOBS_LOCK",
        "SCRIPT_ASSISTANT_JOBS",
        "SCRIPT_ASSISTANT_JOBS_LOCK",
        "SCRIPT_ASSISTANT_PROPOSALS",
        "SCRIPT_ASSISTANT_SUMMARY_CACHE",
        "SCRIPT_ASSISTANT_SUMMARY_CACHE_LOCK",
        "WORKER_RESULT_PREFIX",
    ],
)
