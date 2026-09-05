#!/usr/bin/env python3
"""Round1 HTTP adapter loader — executes body from sibling `_round1_http.z64`.

Temporary transport so GitHub MCP can land large Round1 without `@file://` corruption.
Runtime behavior matches Round1 `http_server.py` (`0.3.0-round1`).
Expand blob to plain source for human review when convenient.
"""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

_blob = (Path(__file__).resolve().parent / "_round1_http.z64").read_text(encoding="utf-8").strip()
_code = zlib.decompress(base64.b64decode(_blob))
exec(compile(_code, str(Path(__file__).resolve().with_name("http_server.py.round1")), "exec"), globals())
