#!/usr/bin/env python3
"""Gov-write stdio loader — sibling `_gov_write_server.z64.p*` (no @file://). Runtime 0.2.2-gov-write."""
from __future__ import annotations
import base64, zlib
from pathlib import Path
_here = Path(__file__).resolve().parent
_parts = sorted(_here.glob("_gov_write_server.z64.p*"), key=lambda p: int(p.name.rsplit("p", 1)[-1]))
_blob = "".join(p.read_text(encoding="utf-8").strip() for p in _parts)
_code = zlib.decompress(base64.b64decode(_blob))
exec(compile(_code, str(_here / "server.py.gov_write"), "exec"), globals())
