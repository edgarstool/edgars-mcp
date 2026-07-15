# ── MiniMax (mmx) handlers ────────────────────────────────────────────────────

def run_mmx_command(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["mmx"] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def handle_mmx_image_generate(req_id, arguments: dict) -> dict:
    prompt = arguments.get("prompt", "").strip()
    if not prompt:
        return make_response(req_id, make_tool_text_response("Error: prompt is required", is_error=True))
    args = ["image", "generate", "--prompt", prompt, "--output", "json", "--quiet"]
    if arguments.get("aspect_ratio"):
        args += ["--aspect-ratio", arguments["aspect_ratio"]]
    if arguments.get("n"):
        args += ["--n", str(arguments["n"])]
    if arguments.get("out_dir"):
        args += ["--out-dir", arguments["out_dir"]]
    try:
        result = run_mmx_command(args)
        if result.returncode != 0:
            return make_response(req_id, make_tool_text_response(f"mmx error: {result.stderr}", is_error=True))
        return make_response(req_id, make_tool_text_response(f"Image(s) generated:\n{result.stdout.strip()}"))
    except subprocess.TimeoutExpired:
        return make_response(req_id, make_tool_text_response("mmx image generate timed out", is_error=True))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_mmx_video_generate(req_id, arguments: dict) -> dict:
    prompt = arguments.get("prompt", "").strip()
    if not prompt:
        return make_response(req_id, make_tool_text_response("Error: prompt is required", is_error=True))
    args = ["video", "generate", "--prompt", prompt, "--output", "json", "--quiet"]
    if arguments.get("async"):
        args += ["--async"]
    if arguments.get("first_frame"):
        args += ["--first-frame", arguments["first_frame"]]
    if arguments.get("download"):
        args += ["--download", arguments["download"]]
    try:
        result = run_mmx_command(args, timeout=300)
        if result.returncode != 0:
            return make_response(req_id, make_tool_text_response(f"mmx error: {result.stderr}", is_error=True))
        return make_response(req_id, make_tool_text_response(f"Video generation:\n{result.stdout.strip()}"))
    except subprocess.TimeoutExpired:
        return make_response(req_id, make_tool_text_response("mmx video generate timed out (5min)", is_error=True))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_mmx_speech_synthesize(req_id, arguments: dict) -> dict:
    text = arguments.get("text", "").strip()
    text_file = arguments.get("text_file", "").strip()
    if not text and not text_file:
        return make_response(req_id, make_tool_text_response("Error: text or text_file is required", is_error=True))
    args = ["speech", "synthesize", "--output", "json", "--quiet"]
    if text:
        args += ["--text", text]
    if text_file:
        args += ["--text-file", text_file]
    if arguments.get("voice"):
        args += ["--voice", arguments["voice"]]
    if arguments.get("model"):
        args += ["--model", arguments["model"]]
    if arguments.get("speed"):
        args += ["--speed", str(arguments["speed"])]
    if arguments.get("format"):
        args += ["--format", arguments["format"]]
    if arguments.get("out"):
        args += ["--out", arguments["out"]]
    try:
        result = run_mmx_command(args)
        if result.returncode != 0:
            return make_response(req_id, make_tool_text_response(f"mmx error: {result.stderr}", is_error=True))
        return make_response(req_id, make_tool_text_response(f"Speech synthesized:\n{result.stdout.strip()}"))
    except subprocess.TimeoutExpired:
        return make_response(req_id, make_tool_text_response("mmx speech synthesize timed out", is_error=True))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_mmx_music_generate(req_id, arguments: dict) -> dict:
    prompt = arguments.get("prompt", "").strip()
    lyrics = arguments.get("lyrics", "").strip()
    if not prompt and not lyrics:
        return make_response(req_id, make_tool_text_response("Error: prompt or lyrics is required", is_error=True))
    args = ["music", "generate", "--output", "json", "--quiet"]
    if prompt:
        args += ["--prompt", prompt]
    if lyrics:
        args += ["--lyrics", lyrics]
    if arguments.get("vocals"):
        args += ["--vocals", arguments["vocals"]]
    if arguments.get("genre"):
        args += ["--genre", arguments["genre"]]
    if arguments.get("mood"):
        args += ["--mood", arguments["mood"]]
    if arguments.get("instruments"):
        args += ["--instruments", arguments["instruments"]]
    if arguments.get("bpm"):
        args += ["--bpm", str(arguments["bpm"])]
    if arguments.get("instrumental"):
        args += ["--instrumental"]
    if arguments.get("out"):
        args += ["--out", arguments["out"]]
    try:
        result = run_mmx_command(args, timeout=180)
        if result.returncode != 0:
            return make_response(req_id, make_tool_text_response(f"mmx error: {result.stderr}", is_error=True))
        return make_response(req_id, make_tool_text_response(f"Music generated:\n{result.stdout.strip()}"))
    except subprocess.TimeoutExpired:
        return make_response(req_id, make_tool_text_response("mmx music generate timed out (3min)", is_error=True))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_mmx_vision_describe(req_id, arguments: dict) -> dict:
    image = arguments.get("image", "").strip()
    file_id = arguments.get("file_id", "").strip()
    if not image and not file_id:
        return make_response(req_id, make_tool_text_response("Error: image or file_id is required", is_error=True))
    args = ["vision", "describe", "--output", "json"]
    if image:
        args += ["--image", image]
    if file_id:
        args += ["--file-id", file_id]
    if arguments.get("prompt"):
        args += ["--prompt", arguments["prompt"]]
    try:
        result = run_mmx_command(args)
        if result.returncode != 0:
            return make_response(req_id, make_tool_text_response(f"mmx error: {result.stderr}", is_error=True))
        return make_response(req_id, make_tool_text_response(result.stdout.strip()))
    except subprocess.TimeoutExpired:
        return make_response(req_id, make_tool_text_response("mmx vision describe timed out", is_error=True))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_mmx_search_query(req_id, arguments: dict) -> dict:
    q = arguments.get("q", "").strip()
    if not q:
        return make_response(req_id, make_tool_text_response("Error: q (query) is required", is_error=True))
    args = ["search", "query", "--q", q, "--output", "json", "--quiet"]
    try:
        result = run_mmx_command(args)
        if result.returncode != 0:
            return make_response(req_id, make_tool_text_response(f"mmx error: {result.stderr}", is_error=True))
        return make_response(req_id, make_tool_text_response(result.stdout.strip()))
    except subprocess.TimeoutExpired:
        return make_response(req_id, make_tool_text_response("mmx search timed out", is_error=True))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_mmx_text_chat(req_id, arguments: dict) -> dict:
    message = arguments.get("message", "").strip()
    if not message:
        return make_response(req_id, make_tool_text_response("Error: message is required", is_error=True))
    args = ["text", "chat", "--message", message, "--output", "json", "--quiet"]
    if arguments.get("system"):
        args += ["--system", arguments["system"]]
    if arguments.get("model"):
        args += ["--model", arguments["model"]]
    if arguments.get("max_tokens"):
        args += ["--max-tokens", str(arguments["max_tokens"])]
    if arguments.get("temperature"):
        args += ["--temperature", str(arguments["temperature"])]
    try:
        result = run