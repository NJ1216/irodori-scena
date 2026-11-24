from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from server.app import app


target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parents[1] / "tests" / "fixtures" / "openapi.json"
schema = app.openapi()
target.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
digest = hashlib.sha256(json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
hash_target = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parents[1] / "src" / "generated" / "api-schema-hash.ts"
if len(sys.argv) <= 1 or len(sys.argv) > 2:
    hash_target.write_text(f'export const API_SCHEMA_HASH = "{digest}" as const;\n', encoding="utf-8", newline="\n")
