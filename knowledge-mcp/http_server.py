#!/usr/bin/env python3
"""Round2 HTTP adapter loader — executes body from sibling `_round2_http.z64` parts.

No `@file://` placeholders. Runtime: `0.3.0-round2` (loads Round2 server body).
"""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_round2_http.z64.p*"), key=lambda p: int(p.name.rsplit("p", 1)[-1]))
if _parts:
    _blob = "".join(p.read_text(encoding="utf-8").strip() for p in _parts)
else:
    _blob = (_here / "_round2_http.z64").read_text(encoding="utf-8").strip()
_code = zlib.decompress(base64.b64decode(_blob))
exec(compile(_code, str(_here / "http_server.py.round2"), "exec"), globals())
