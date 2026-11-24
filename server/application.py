from __future__ import annotations

import hmac
import logging
import os
import signal
import threading
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from server.app_deps import CORSMiddleware, FastAPI
from server.access_logging import install_access_log_filter
from server.registry import deps
from server.input_diagnostics import install_input_diagnostics


LOGGER = logging.getLogger(__name__)
INTERNAL_ERROR_DETAIL = {
    "code": "internal_server_error",
    "message": "アプリ内部の処理エラーが発生しました。",
}


def install_internal_error_boundary(application: FastAPI) -> None:
    @application.middleware("http")
    async def handle_unhandled_error(request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as error:
            LOGGER.exception("Unhandled API error for %s %s", request.method, request.url.path, exc_info=error)
            return JSONResponse(status_code=500, content={"detail": INTERNAL_ERROR_DETAIL})


def create_base_app() -> FastAPI:
    install_access_log_filter()
    desktop = os.environ.get("SCENA_DESKTOP") == "1"
    token = os.environ.get("SCENA_API_TOKEN", "")
    if desktop and not token:
        raise RuntimeError("SCENA_API_TOKEN is required when SCENA_DESKTOP=1")
    application = FastAPI(title="irodori SCENA Local API", version="0.1.0")

    install_internal_error_boundary(application)
    if os.environ.get("SCENA_DEV_MODE") == "1":
        install_input_diagnostics(application)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173", "http://localhost:5173",
            "http://127.0.0.1:5175", "http://localhost:5175",
            "tauri://localhost", "http://tauri.localhost",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-SCENA-History-Scope"],
    )

    if desktop:
        @application.middleware("http")
        async def require_desktop_token(request: Request, call_next):
            if request.method == "OPTIONS" or not request.url.path.startswith("/api/"):
                return await call_next(request)
            supplied = request.headers.get("authorization", "")
            expected = f"Bearer {token}"
            if not hmac.compare_digest(supplied.encode(), expected.encode()):
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return await call_next(request)

        parent_pid = int(os.environ.get("SCENA_PARENT_PID", "0"))
        if parent_pid <= 1:
            raise RuntimeError("SCENA_PARENT_PID is required when SCENA_DESKTOP=1")

        def watch_parent() -> None:
            while True:
                time.sleep(1)
                try:
                    os.kill(parent_pid, 0)
                except ProcessLookupError:
                    os.kill(os.getpid(), signal.SIGTERM)
                    return
                except PermissionError:
                    continue

        if os.name != "nt":
            threading.Thread(target=watch_parent, name="scena-parent-watchdog", daemon=True).start()
        elif not os.environ.get("SCENA_CONTROL_ADDRESS"):
            raise RuntimeError("Windows desktop requires its parent control connection")
    return application


app = create_base_app()
deps.register(__name__, ["app"])
