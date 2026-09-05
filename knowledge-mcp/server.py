#!/usr/bin/env python3
"""Round1 stdio adapter loader — executes body from sibling `_round1_server.z64`.

Temporary transport so GitHub MCP can land large Round1 without `@file://` corruption.
Runtime behavior matches Round1 `server.py` (`0.2.0-round1`, includes `knowledge_context_pack`).
Expand blob to plain source for human review when convenient:

```bash
python3 - <<'PY'
import base64, zlib
from pathlib import Path
p = Path('knowledge-mcp')
p.joinpath('server.py').write_bytes(
    zlib.decompress(base64.b64decode(p.joinpath('_round1_server.z64').read_text().strip()))
)
p.joinpath('http_server.py').write_bytes(
    zlib.decompress(base64.b64decode(p.joinpath('_round1_http.z64').read_text().strip()))
)
print('expanded')
PY
```
"""
from __future__ import annotations

import base64
import zlib
from pathlib import Path

_blob = (Path(__file__).resolve().parent / "_round1_server.z64").read_text(encoding="utf-8").strip()
_code = zlib.decompress(base64.b64decode(_blob))
exec(compile(_code, str(Path(__file__).resolve().with_name("server.py.round1")), "exec"), globals())
