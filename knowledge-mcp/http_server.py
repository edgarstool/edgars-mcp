#!/usr/bin/env python3
"""Round1 HTTP adapter loader — joins `_round1_http.z64.p0..p3` then execs.

Parts avoid GitHub MCP single-byte corruption seen on monolithic ~8k blobs.
Runtime = Round1 `0.3.0-round1`.
"""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

_here = Path(__file__).resolve().parent
_blob = "".join((_here / f"_round1_http.z64.p{i}").read_text(encoding="utf-8").strip() for i in range(4))
_code = zlib.decompress(base64.b64decode(_blob))
exec(compile(_code, str(_here / "http_server.py.round1"), "exec"), globals())
