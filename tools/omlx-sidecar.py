"""Frozen entry point for SCENA's deliberately small oMLX runtime."""

import os
import subprocess
import sys
import types


def _install_unused_feature_stubs() -> None:
    """Keep upstream's eager server imports from pulling unused product surfaces."""
    from fastapi import APIRouter

    class RedirectToLogin(Exception):
        pass

    class DistributedInferenceError(RuntimeError):
        pass

    class ClusterDeployment:
        pass

    class DisabledDownloader:
        is_quantizing = False

        def __init__(self, **_kwargs):
            pass

        async def shutdown(self):
            pass

    def fingerprint_key(value: str) -> str:
        import hashlib

        return hashlib.sha256(value.encode("utf-8", "surrogatepass")).hexdigest()[:8]

    def verify_any_api_key(value: str, primary: str, sub_keys: list) -> bool:
        import secrets

        candidates = [primary, *(item.get("key", "") if isinstance(item, dict) else "" for item in sub_keys)]
        return any(candidate and secrets.compare_digest(value, candidate) for candidate in candidates)

    modules: dict[str, dict[str, object]] = {
        "omlx.admin": {"__path__": []},
        "omlx.api.mcp_routes": {
            "router": APIRouter(), "set_mcp_manager_getter": lambda _getter: None,
        },
        "omlx.api.websearch_routes": {
            "router": APIRouter(), "set_global_settings_getter": lambda _getter: None,
        },
        "omlx.admin.auth": {
            "_RedirectToLogin": RedirectToLogin,
            "require_admin": lambda: True,
            "init_auth": lambda *_args: None,
            "fingerprint_key": fingerprint_key,
            "verify_any_api_key": verify_any_api_key,
        },
        "omlx.admin.routes": {
            "router": APIRouter(), "set_admin_getters": lambda *_getters: None,
            "_refresh_i18n_globals": lambda: None,
            "set_hf_downloader": lambda _downloader: None,
            "set_ms_downloader": lambda _downloader: None,
            "set_oq_manager": lambda _manager: None,
            "set_hf_uploader": lambda _uploader: None,
        },
        "omlx.admin.hf_downloader": {"HFDownloader": DisabledDownloader},
        "omlx.admin.ms_downloader": {
            "MS_SDK_AVAILABLE": False, "MSDownloader": DisabledDownloader,
        },
        "omlx.admin.oq_manager": {"OQManager": DisabledDownloader},
        "omlx.admin.hf_uploader": {"HFUploader": DisabledDownloader},
        "omlx.cluster": {"__path__": []},
        "omlx.cluster.discovery": {
            "BonjourPublisher": type("BonjourPublisher", (), {
                "__init__": lambda self, **_kwargs: None,
                "start": lambda self: None, "stop": lambda self: None,
                "ensure_running": lambda self: None,
            }),
        },
        "omlx.cluster.worker_shim": {"ensure_cluster_python_shim": lambda: None},
        "omlx.cluster.exposure": {"distributed_inference_enabled": lambda _settings: False},
        "omlx.cluster.deployment": {"ClusterDeployment": ClusterDeployment},
        "omlx.cluster.registry": {"configure_cluster_registry": lambda _path: None},
        "omlx.cluster.enrollment": {"configure_cluster_enrollment": lambda _path: None},
        "omlx.cluster.incidents": {"configure_cluster_incidents": lambda _path: None},
        "omlx.cluster.strategy_benchmarks": {
            "configure_strategy_benchmark_store": lambda _path: None,
        },
        "omlx.engine.distributed": {
            "DistributedInferenceError": DistributedInferenceError,
        },
    }
    for name, members in modules.items():
        module = types.ModuleType(name)
        vars(module).update(members)
        sys.modules[name] = module


_install_unused_feature_stubs()

from omlx.cli import main  # noqa: E402


def install_frozen_compile_cache_resolver() -> None:
    """Point oMLX at PyInstaller's single, top-level libmlx copy."""
    import ctypes
    import logging
    from pathlib import Path

    import omlx.utils.compile_cache as compile_cache

    def resolve_clear_fn():
        if compile_cache._resolved:
            return compile_cache._clear_fn
        with compile_cache._resolve_lock:
            if compile_cache._resolved:
                return compile_cache._clear_fn
            compile_cache._resolved = True
            try:
                frozen_root = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
                libmlx = frozen_root / "libmlx.dylib"
                lib = ctypes.PyDLL(str(libmlx))
                for name in (compile_cache._CLEAR_SYMBOL, "_" + compile_cache._CLEAR_SYMBOL):
                    try:
                        function = getattr(lib, name)
                        break
                    except AttributeError:
                        function = None
                if function is None:
                    raise AttributeError(compile_cache._CLEAR_SYMBOL)
                function.restype = None
                function.argtypes = []
                compile_cache._clear_fn = function
                logging.getLogger(compile_cache.__name__).info(
                    "MLX compile-cache clear resolved (%s)", compile_cache._CLEAR_SYMBOL
                )
            except (OSError, AttributeError) as error:
                logging.getLogger(compile_cache.__name__).warning(
                    "MLX compile-cache clear unavailable (%s); MLX worker threads "
                    "will remain alive as a safe fallback", error
                )
                compile_cache._clear_fn = None
            return compile_cache._clear_fn

    compile_cache._resolve_clear_fn = resolve_clear_fn


def install_metrics_route() -> None:  # noqa: C901
    import mlx.core as mx

    from fastapi import Body, Depends, HTTPException
    from omlx.server import _server_state, app, verify_api_key

    def resident_memory() -> int:
        try:
            return max(0, int(subprocess.check_output(
                ["ps", "-o", "rss=", "-p", str(__import__("os").getpid())], text=True
            ).strip()) * 1024)
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0

    baseline_resident = resident_memory()

    def loaded_engine(model_id: str):
        pool = getattr(_server_state, "engine_pool", None)
        entries = getattr(pool, "_entries", {}) if pool is not None else {}
        entry = entries.get(model_id) if isinstance(entries, dict) else None
        return getattr(entry, "engine", entry)

    def scheduler_for(model_id: str):
        engine = loaded_engine(model_id)
        inner = getattr(engine, "_engine", None)
        core = getattr(inner, "engine", inner)
        return getattr(core, "scheduler", None)

    @app.get("/api/scena/metrics", include_in_schema=False)
    async def scena_metrics(_: bool = Depends(verify_api_key)) -> dict[str, int]:
        """Expose only the in-process MLX allocation needed by SCENA."""
        active = max(0, int(mx.get_active_memory()))
        resident_growth = max(0, resident_memory() - baseline_resident)
        return {"activeMemoryBytes": active, "modelMemoryBytes": max(active, resident_growth)}

    @app.get("/api/scena/models/{model_id:path}/cache-metrics", include_in_schema=False)
    async def scena_cache_metrics(model_id: str, _: bool = Depends(verify_api_key)) -> dict[str, object]:
        """Expose aggregate cache counters without prompt text or KV payloads."""
        from omlx.server_metrics import get_server_metrics

        # SCENA's managed card id can differ from oMLX's resolved serving id.
        # The bundled server is strictly serial, so global deltas are request-local.
        server_metrics = get_server_metrics()
        snapshot = server_metrics.get_snapshot()
        result = {
            "requests": snapshot.get("total_requests", 0),
            "prompt_tokens": snapshot.get("total_prompt_tokens", 0),
            "completion_tokens": snapshot.get("total_completion_tokens", 0),
            "cached_tokens": snapshot.get("total_cached_tokens", 0),
            "prefill_duration": server_metrics.total_prefill_duration,
            "generation_duration": server_metrics.total_generation_duration,
        }
        scheduler = scheduler_for(model_id)
        cache = scheduler.get_ssd_cache_stats() if scheduler is not None else None
        prefix = cache.get("prefix_cache", {}) if isinstance(cache, dict) else {}
        ssd = cache.get("ssd_cache") if isinstance(cache, dict) else None
        for source, target in (
            ("hits", "prefix_hits"), ("misses", "prefix_misses"),
            ("tokens_saved", "prefix_tokens_saved"),
        ):
            value = prefix.get(source) if isinstance(prefix, dict) else None
            if isinstance(value, int):
                result[target] = value
        for source, target in (
            ("hot_cache_evictions", "hot_cache_evictions"),
            ("hot_cache_size_bytes", "hot_cache_size_bytes"),
            ("saves_persisted", "ssd_saves"), ("total_size_bytes", "ssd_size_bytes"),
        ):
            value = getattr(ssd, source, None)
            if isinstance(value, int):
                result[target] = value
        block_size = cache.get("block_size") if isinstance(cache, dict) else None
        if isinstance(block_size, int):
            result["cache_block_size"] = block_size
        result["active_memory_bytes"] = int(mx.get_active_memory())
        result["peak_memory_bytes"] = int(mx.get_peak_memory())
        return result

    @app.post("/api/scena/benchmark/reset-peak-memory", include_in_schema=False)
    async def scena_reset_peak_memory(_: bool = Depends(verify_api_key)) -> dict[str, int]:
        """Reset process-global MLX peak tracking for a serial benchmark request."""
        mx.reset_peak_memory()
        return {"active_memory_bytes": int(mx.get_active_memory())}

    @app.put("/api/scena/models/{model_id:path}/settings", include_in_schema=False)
    async def scena_model_settings(
        model_id: str, values: dict = Body(...), _: bool = Depends(verify_api_key)
    ) -> dict[str, str]:
        """Apply the small, reviewed subset of oMLX model settings SCENA exposes."""
        manager = _server_state.settings_manager
        if manager is None:
            raise HTTPException(status_code=503, detail="Model settings are not ready")
        settings = manager.get_settings(model_id)
        settings.max_context_window = values.get("max_context_window")
        settings.ttl_seconds = values.get("ttl_seconds")
        settings.enable_thinking = bool(values.get("enable_thinking"))
        settings.trust_remote_code = bool(values.get("trust_remote_code"))
        settings.mtp_enabled = bool(values.get("mtp_enabled"))
        settings.vlm_mtp_enabled = bool(values.get("vlm_mtp_enabled"))
        settings.vlm_mtp_draft_model = values.get("vlm_mtp_draft_model")
        manager.set_settings(model_id, settings)
        return {"status": "ok"}

    @app.get("/api/scena/models/{model_id:path}/engine", include_in_schema=False)
    async def scena_model_engine(model_id: str, _: bool = Depends(verify_api_key)) -> dict[str, object]:
        settings = _server_state.settings_manager.get_settings(model_id)
        engine = loaded_engine(model_id)
        drafter = getattr(engine, "vlm_mtp_drafter", None)
        drafter = drafter() if callable(drafter) else drafter
        return {"model": model_id, "engine": type(engine).__name__ if engine is not None else None,
                "vlmMtpEnabled": bool(settings.vlm_mtp_enabled),
                "mtpDraftModel": str(settings.vlm_mtp_draft_model) if settings.vlm_mtp_draft_model else None,
                "mtpActive": drafter is not None}


def restrict_routes() -> None:
    """Expose only the stable oMLX surface consumed by SCENA."""
    from omlx.server import app

    allowed = {
        "/health", "/v1/models", "/v1/models/status",
        "/v1/chat/completions",
    }
    allowed_prefixes = ("/v1/models/", "/api/scena/")
    app.router.routes[:] = [
        route for route in app.router.routes
        if getattr(route, "path", "") in allowed
        or getattr(route, "path", "").startswith(allowed_prefixes)
    ]


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        install_frozen_compile_cache_resolver()
        install_metrics_route()
        restrict_routes()
        os.environ.pop("OMLX_MCP_CONFIG", None)
    main()
