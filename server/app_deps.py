from __future__ import annotations

import atexit
import difflib
import hashlib
import http.client
import json
import io
import math
import os
from queue import Empty, Queue
import re
import secrets
import shutil
from server import subprocess_boundary as subprocess
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from base64 import b64decode
from pathlib import Path
from typing import Any, Callable, Iterator, Literal
from urllib.parse import quote, urlsplit
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
import keyring

from server.draft_protocol import (
    parse_context_selection,
    parse_dialogue_protocol,
    parse_performance_protocol,
    parse_plan_protocol,
)
