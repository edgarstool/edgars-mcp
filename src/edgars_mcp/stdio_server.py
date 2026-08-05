import sys
import json

# ── Windows: 確保 stdin/stdout 是 binary 模式再包裝成 utf-8 文字流 ──────────
# 不做這步，Windows 會把 \n 轉成 \r\n、或插入 BOM，導致 JSON parse 失敗。
if sys.platform == "win32":
    import msvcrt, os
    msvcrt.setmode(sys.stdin.fileno(),  os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    sys.stdin  = open(sys.stdin.fileno(),  "r", encoding="utf-8", newline="\n", closefd=False)
    sys.stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)


def log(msg):
    print(f"[MCP] {msg}", file=sys.stderr, flush=True)

def send(response):
    line = json.dumps(response, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    log(f"SEND → {line}")

def send_response(req_id, result):
    send({"jsonrpc": "2.0", "id": req_id, "result": result})

def send_error(req_id, code, message):
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})

def handle_initialize(msg):
    log("initialize received")
    send_response(msg["id"], {
        "protocolVersion": "2025-11-25",
        "capabilities": {"tools": {}},
        "serverInfo": {"name": "edgars-mcp", "version": "0.1.0"}
    })

def handle_tools_list(msg):
    log("tools/list received")
    send_response(msg["id"], {
        "tools": [{
            "name": "echo",
            "description": "Echoes back the input message",
            "inputSchema": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"]
            }
        }]
    })

def handle_tools_call(msg):
    log("tools/call received")
    args = msg.get("params", {}).get("arguments", {})
    name = msg.get("params", {}).get("name", "")
    if name == "echo":
        text = args.get("message", "")
        send_response(msg["id"], {
            "content": [{"type": "text", "text": f"echo: {text}"}],
            "isError": False
        })
    else:
        send_error(msg["id"], -32601, f"Tool not found: {name}")

def handle_ping(msg):
    log("ping received")
    send_response(msg["id"], {})

def handle_request(msg):
    method = msg.get("method", "")
    log(f"request: {method}")
    if method == "initialize":
        handle_initialize(msg)
    elif method == "tools/list":
        handle_tools_list(msg)
    elif method == "tools/call":
        handle_tools_call(msg)
    elif method == "ping":
        handle_ping(msg)
    else:
        send_error(msg.get("id"), -32601, f"Method not found: {method}")

def handle_notification(msg):
    log(f"notification: {msg.get('method')} (ignored)")

def dispatch(msg):
    if "id" in msg:
        handle_request(msg)
    else:
        handle_notification(msg)

def main():
    log("edgars-mcp server started")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            dispatch(msg)
        except json.JSONDecodeError as e:
            log(f"parse error: {e}")
            send_error(None, -32700, "Parse error")

if __name__ == "__main__":
    main()
