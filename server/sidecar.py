"""FastAPI desktop entry point with platform-specific socket ownership."""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from server.uvicorn_options import UVICORN_PROTOCOLS


def main() -> None:
    # Release bundles include only the credential backend for their host OS.
    if sys.platform == "darwin":
        os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.macOS.Keyring")
    elif sys.platform == "win32":
        os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.Windows.WinVaultKeyring")
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-user-data", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--error-log", help=argparse.SUPPRESS)
    parser.add_argument("--host", default="127.0.0.1")
    binding = parser.add_mutually_exclusive_group()
    binding.add_argument("--port", type=int)
    binding.add_argument("--fd", type=int)
    options = parser.parse_args()
    if options.cleanup_user_data:
        from server.windows_uninstall_cleanup import run_cleanup

        raise SystemExit(run_cleanup(options.error_log))

    from server.app import app

    if os.environ.get("SCENA_CONTROL_ADDRESS"):
        from server.desktop_control import run_desktop

        try:
            run_desktop(app)
        except ConnectionRefusedError:
            # The desktop parent can exit while a bundled Python runtime is
            # still starting. Its private listener is then intentionally gone.
            return
        return
    if options.port is None and options.fd is None:
        parser.error("one of --port or --fd is required")
    uvicorn.run(app, host=options.host, port=options.port or 0, fd=options.fd, log_level="info", access_log=False,
                **UVICORN_PROTOCOLS)


if __name__ == "__main__":
    main()
