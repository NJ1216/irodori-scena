"""Uvicorn protocol choices for the bundled API.

The API serves no WebSocket routes and runs on the standard asyncio loop. Naming both stops Uvicorn
from probing for optional packages: a leftover websockets or uvloop folder (an in-place Windows
install once left websockets/speedups.pyd behind) imports as an empty namespace and breaks startup.
"""

UVICORN_PROTOCOLS: dict[str, str] = {"loop": "asyncio", "ws": "none"}
