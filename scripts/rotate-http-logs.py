# -*- coding: utf-8 -*-
"""
輪替 handcraft-http log：超過門檻就 .log -> .log.1 -> .log.2 -> .log.3（最舊的刪除）。
由 run_http.cmd 在 MCP 啟動前呼叫。用法：
    py -3 rotate-http-logs.py [max_bytes]   # 預設 5MB
"""
import os
import sys

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
TARGETS = ["handcraft-http.err.log", "handcraft-http.out.log"]
KEEP = 3


def rotate(path: str, max_bytes: int) -> bool:
    if not os.path.isfile(path) or os.path.getsize(path) < max_bytes:
        return False
    oldest = f"{path}.{KEEP}"
    if os.path.isfile(oldest):
        os.remove(oldest)
    for i in range(KEEP - 1, 0, -1):
        src = f"{path}.{i}"
        if os.path.isfile(src):
            os.replace(src, f"{path}.{i + 1}")
    os.replace(path, f"{path}.1")
    return True


def main():
    max_bytes = int(sys.argv[1]) if len(sys.argv) > 1 else 5 * 1024 * 1024
    for name in TARGETS:
        p = os.path.join(LOGS_DIR, name)
        try:
            if rotate(p, max_bytes):
                print(f"[rotate] {name} -> {name}.1")
        except OSError as e:
            print(f"[rotate] {name} 失敗（可能被占用）: {e}")


if __name__ == "__main__":
    main()
