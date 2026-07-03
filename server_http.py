"""
手刻 MCP Server - Streamable HTTP 版本
協議版本: 2025-11-25
依賴: Python 標準庫；啟用 Cloudflare Access 模式時額外使用 PyJWT

端點:
- POST /mcp
- POST /webhook/package
- POST /webhook/linear
- GET  /linear/oauth/authorize
- GET  /linear/oauth/callback
- GET  /linear/oauth/status
回應模式: 單次 JSON（不開 SSE stream，Phase 2 基礎版）
"""

import sys
import json
import os
import subprocess
import tempfile
import threading
import time
import uuid
import shutil
import base64
import hashlib
import hmac
import secrets
import urllib.parse
import urllib.error
import urllib.request
import fnmatch
import platform
import re
import string
import datetime
import zipfile
from html import escape as html_escape
from dataclasses import dataclass
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from mmx_handlers import DISPATCH, hmi, hmvd, hms, hmu, hmv, hmsq, hmc, hmq

try:
    import jwt
    from jwt import InvalidTokenError, PyJWKClient
except ImportError:  # pragma: no cover - optional dependency in legacy mode
    jwt = None
    InvalidTokenError = Exception
    PyJWKClient = None

# ── mmx handler aliases（對應 dispatch 的完整名稱）─────────────────────────────
handle_mmx_image_generate   = hmi
handle_mmx_video_generate   = hmv
handle_mmx_speech_synthesize = hms
handle_mmx_music_generate   = hmu
handle_mmx_vision_describe  = hmvd
handle_mmx_search_query     = hmsq
handle_mmx_text_chat        = hmc
handle_mmx_quota_show       = hmq

# ── Secrets（由 Doppler 注入）─────────────────────────────────────────────────
def load_mcp_api_token() -> str:
    return os.getenv("MCP_API_TOKEN", "").strip()


def load_base_url() -> str:
    return os.getenv("MCP_BASE_URL", "https://mcp.edgars.tools").strip()


def load_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def load_webhook_base_url() -> str:
    return os.getenv("MCP_WEBHOOK_BASE_URL", "").strip()


def load_cloudflare_access_team_domain() -> str:
    return os.getenv("MCP_CLOUDFLARE_ACCESS_TEAM_DOMAIN", "").strip()


def load_cloudflare_access_aud() -> str:
    return os.getenv("MCP_CLOUDFLARE_ACCESS_AUD", "").strip()


def load_cloudflare_access_jwks_url() -> str:
    return os.getenv("MCP_CLOUDFLARE_ACCESS_JWKS_URL", "").strip()


def load_package_webhook_token() -> str:
    return os.getenv("MCP_PACKAGE_WEBHOOK_TOKEN", "").strip()


def load_linear_webhook_token() -> str:
    return os.getenv("MCP_LINEAR_WEBHOOK_TOKEN", "").strip()


def load_discord_webhook_token() -> str:
    return os.getenv("MCP_DISCORD_WEBHOOK_TOKEN", "").strip()


@dataclass(frozen=True)
class HandcraftServerConfig:
    mcp_api_token: str
    base_url: str
    webhook_base_url: str = ""
    cloudflare_access_enabled: bool = False
    cloudflare_access_team_domain: str = ""
    cloudflare_access_aud: str = ""
    cloudflare_access_jwks_url: str = ""
    cloudflare_access_disable_builtin_oauth: bool = True
    cloudflare_access_allow_public_token_fallback: bool = False
    package_webhook_token: str = ""
    linear_webhook_token: str = ""
    discord_webhook_token: str = ""

    @property
    def public_hostname(self) -> str:
        return (urllib.parse.urlparse(self.base_url).hostname or "").lower()

    @property
    def webhook_hostname(self) -> str:
        candidate = self.webhook_base_url or self.base_url
        return (urllib.parse.urlparse(candidate).hostname or "").lower()

    @property
    def cloudflare_access_issuer(self) -> str:
        if not self.cloudflare_access_team_domain:
            return ""
        return f"https://{self.cloudflare_access_team_domain}"


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

    def __init__(self, server_address, RequestHandlerClass, config: HandcraftServerConfig):
        super().__init__(server_address, RequestHandlerClass)
        self.config = config


NOTION_API_KEY      = os.getenv("NOTION_API_KEY", "")
PERPLEXITY_API_KEY  = os.getenv("PERPLEXITY_API_KEY", "")
OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY", "")
LINEAR_API_KEY      = os.getenv("LINEAR_API_KEY", "")
LINEAR_CLIENT_ID    = os.getenv("LINEAR_CLIENT_ID", "").strip()
LINEAR_CLIENT_SECRET = os.getenv("LINEAR_CLIENT_SECRET", "").strip()
LINEAR_WEBHOOK_SECRET = os.getenv("LINEAR_WEBHOOK_SECRET", "").strip()
LINEAR_OAUTH_SCOPES = os.getenv(
    "LINEAR_OAUTH_SCOPES",
    "read,write,app:assignable,app:mentionable",
).strip()
LINEAR_OAUTH_CALLBACK_PATH = "/linear/oauth/callback"
LINEAR_OAUTH_AUTHORIZE_PATH = "/linear/oauth/authorize"
LINEAR_OAUTH_STATUS_PATH = "/linear/oauth/status"
LINEAR_OAUTH_BOOTSTRAP_PATH = "/linear/oauth/bootstrap"
LINEAR_OAUTH_FORCE_CONSENT = os.getenv("LINEAR_OAUTH_FORCE_CONSENT", "true").strip().lower() in {
    "1", "true", "yes", "on",
}
LINEAR_OAUTH_TOKEN_FILE = Path(__file__).resolve().parent / "config" / "linear-oauth-token.json"
LINEAR_OAUTH_REDIRECT_URI = os.getenv(
    "LINEAR_OAUTH_REDIRECT_URI",
    "https://mcp.edgars.tools/linear/oauth/callback",
).strip()
LINEAR_TOKEN_URL = "https://api.linear.app/oauth/token"
LINEAR_AUTHORIZE_URL = "https://linear.app/oauth/authorize"
TRACKTW_API_KEY     = os.getenv("TRACKTW_API_KEY", "")
WARP_API_KEY        = os.getenv("WARP_API_KEY", "")
CURSOR_API_KEY      = os.getenv("CURSOR_API_KEY", "")
FACTORY_API_KEY     = os.getenv("FACTORY_API_KEY", "")

REPO_ROOT = Path(__file__).resolve().parent
_VAULT_CANONICAL = Path(r"G:\Obsidian\Edgar'sObsidianVault")
_VAULT_FALLBACK = Path(r"G:\AgentKB\Obsidian\Edgar'sObsidianVault")


def _resolve_vault_root() -> Path:
    override = os.getenv("OBSIDIAN_VAULT_ROOT", "").strip()
    if override:
        return Path(override)
    for candidate in (_VAULT_CANONICAL, _VAULT_FALLBACK):
        if candidate.is_dir():
            return candidate
    return _VAULT_CANONICAL


SCREENSHOTS_DIR = REPO_ROOT / ".screenshots"
REPORTS_DIR     = REPO_ROOT / "reports"
VAULT_ROOT      = _resolve_vault_root()

CODEX_CMD = r"C:\Users\EdgarsTool\AppData\Roaming\npm\codex.cmd"
CLAUDE_CMD = shutil.which("claude") or "claude"
GEMINI_CMD = shutil.which("gemini") or "gemini"
OLLAMA_CMD = r"C:\Users\EdgarsTool\AppData\Local\Programs\Ollama\ollama.exe"
OLLAMA_HOST_RAW = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip()
OLLAMA_HOST = OLLAMA_HOST_RAW if OLLAMA_HOST_RAW.startswith(("http://", "https://")) else f"http://{OLLAMA_HOST_RAW}"
CODEX_DEFAULT_WORKDIR = r"C:\Users\EdgarsTool"
AGENT_TIMEOUT_SECONDS = int(os.getenv("MCP_AGENT_TIMEOUT_SECONDS", "300"))

PORT = int(os.getenv("MCP_PORT", "8765"))
PROTOCOL_VERSION = "2025-11-25"
MCP_PATH = "/mcp"
HEALTH_PATH = "/health"
PACKAGE_WEBHOOK_PATH = "/webhook/package"
LINEAR_WEBHOOK_PATH = "/webhook/linear"
LINEAR_WEBHOOK_PATH_ALIAS = "/webhooks/linear"  # accept Linear's plural-form URL
DEFAULT_JOB_RETENTION_SECONDS = int(os.getenv("MCP_JOB_RETENTION_SECONDS", "3600"))

CONNECTOR_DISPLAY_NAME = "edgars mcp"

SERVER_INFO = {
    "name": CONNECTOR_DISPLAY_NAME,
    "version": "0.1.0",
}

JOBS_LOCK = threading.Lock()
JOBS: dict[str, dict] = {}
DISCORD_WEBHOOK_EVENTS_LOCK = threading.Lock()
DISCORD_WEBHOOK_EVENTS: list[dict] = []
MAX_DISCORD_WEBHOOK_EVENTS = int(os.getenv("MCP_DISCORD_WEBHOOK_EVENT_LIMIT", "100"))
TRACKTW_BASE_URL = os.getenv("TRACKTW_BASE_URL", "https://track.tw/api/v1").rstrip("/")
WARP_BASE_URL = os.getenv("WARP_BASE_URL", "https://app.warp.dev/api/v1").rstrip("/")
CURSOR_BASE_URL = os.getenv("CURSOR_BASE_URL", "https://api.cursor.com").rstrip("/")
FACTORY_API_BASE_URL = os.getenv("FACTORY_API_BASE_URL", "https://api.factory.ai").rstrip("/")
FACTORY_APP_BASE_URL = os.getenv("FACTORY_APP_BASE_URL", "https://app.factory.ai").rstrip("/")
TRACKTW_STATUS_MODEL_SOURCE = "Google Sheet: TrackTW / tracktw_active + tracktw_events"
TRACKTW_ACTIVE_FIELDS = (
    "enabled",
    "label",
    "carrier_keyword",
    "tracking_number",
    "tracktw_uuid",
    "poll_profile",
    "current_status",
    "current_checkpoint_status",
    "current_event_time",
    "last_checked_at",
    "next_check_after",
    "last_notified_status",
    "last_notified_at",
    "picked_up_at",
    "archive_after",
    "record_state",
    "notify_channel",
    "notify_target",
    "notes",
)
TRACKTW_EVENT_FIELDS = (
    "event_at",
    "label",
    "carrier_keyword",
    "tracking_number",
    "from_status",
    "from_checkpoint_status",
    "to_status",
    "to_checkpoint_status",
    "current_event_time",
    "action",
    "notify_channel",
    "notify_target",
    "message",
)

OAUTH_SCOPE = "mcp"

# ── OAuth 2.0 一次性授權碼（記憶體暫存，重啟後清空）──────────────────────────
OAUTH_CODES_LOCK = threading.Lock()
OAUTH_CODES: dict[str, dict] = {}
OAUTH_CLIENTS_LOCK = threading.Lock()
OAUTH_CLIENTS: dict[str, dict] = {}
OAUTH_TOKENS_LOCK = threading.Lock()
OAUTH_ACCESS_TOKENS: dict[str, dict] = {}
OAUTH_AUTH_CODE_TTL_SECONDS = int(os.getenv("MCP_OAUTH_AUTH_CODE_TTL_SECONDS", "600"))
OAUTH_ACCESS_TOKEN_TTL_SECONDS = int(os.getenv("MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS", "7776000"))
OAUTH_STATIC_CLIENT_ID = os.getenv("MCP_OAUTH_CLIENT_ID", "handcraft-mcp").strip() or "handcraft-mcp"
OAUTH_STATIC_CLIENT_SECRET = (
    os.getenv("MCP_OAUTH_CLIENT_SECRET", "handcraft-mcp-client-secret").strip()
    or "handcraft-mcp-client-secret"
)
# ChatGPT probes POST /register when registration_endpoint is advertised; empty body → 400
# and the connector aborts before /authorize. Default off — use CIMD (MCP 2025-11-25 preferred).
OAUTH_DCR_ENABLED = load_bool_env("MCP_OAUTH_DCR_ENABLED", False)
# CIMD (Client ID Metadata Document) cache — RFC draft + MCP 2025-11-25.
OAUTH_CIMD_CACHE_LOCK = threading.Lock()
OAUTH_CIMD_CACHE: dict[str, dict] = {}
OAUTH_CIMD_CACHE_TTL_SECONDS = int(os.getenv("MCP_OAUTH_CIMD_CACHE_TTL_SECONDS", "86400"))
OAUTH_CIMD_FETCH_TIMEOUT_SECONDS = float(os.getenv("MCP_OAUTH_CIMD_FETCH_TIMEOUT_SECONDS", "10"))
OAUTH_CIMD_MAX_BYTES = int(os.getenv("MCP_OAUTH_CIMD_MAX_BYTES", str(64 * 1024)))
OAUTH_AUTH_CHATGPT_CIMD_URL = (
    os.getenv(
        "MCP_OAUTH_AUTH_CHATGPT_CIMD_URL",
        "https://auth.edgars.tools/.well-known/oauth-client/chatgpt.json",
    ).strip()
    or "https://auth.edgars.tools/.well-known/oauth-client/chatgpt.json"
)
CHATGPT_CONNECTOR_REDIRECT_PREFIX = "https://chatgpt.com/connector/oauth/"
OAUTH_OIDC_SCOPES = ["openid", "profile", "email", OAUTH_SCOPE]
CLOUDFLARE_ACCESS_JWKS_LOCK = threading.Lock()
CLOUDFLARE_ACCESS_JWKS_CLIENTS: dict[str, object] = {}
TOOLS = [
    {
        "name": "echo",
        "description": "Echoes back the input message",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The message to echo back",
                }
            },
            "required": ["message"],
        },
    },
    {
        "name": "codex_agent",
        "description": (
            "Delegates a task to the Codex AI coding agent running on the local machine. "
            "Codex will autonomously plan, write code, run shell commands, and edit files "
            "to complete the task. Use this when you want another AI agent to handle "
            "implementation work independently. Returns Codex's final response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task or instruction for Codex to execute autonomously",
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        f"Working directory for Codex to operate in "
                        f"(default: {CODEX_DEFAULT_WORKDIR})"
                    ),
                },
                "async": {
                    "type": "boolean",
                    "description": (
                        "When true, starts the task in the background and returns a job_id "
                        "immediately. Recommended for long-running tasks or clients with short HTTP timeouts."
                    ),
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "gemini_agent",
        "description": (
            "Delegates a task to the Gemini CLI AI agent running on the local machine. "
            "Fast response (under 30 seconds). Best for quick coding tasks, file operations, "
            "shell commands, and general automation on the local Windows machine. "
            "Use this as the default agent for most tasks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task or instruction for Gemini to execute",
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        f"Working directory for Gemini to operate in "
                        f"(default: {CODEX_DEFAULT_WORKDIR})"
                    ),
                },
                "async": {
                    "type": "boolean",
                    "description": (
                        "When true, starts the task in the background and returns a job_id "
                        "immediately. Recommended when the client may timeout before the task finishes."
                    ),
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "claude_code_agent",
        "description": (
            "Delegates a task to the Claude Code AI coding agent running on the local machine. "
            "Claude Code will autonomously plan, write code, run shell commands, and edit files "
            "to complete the task. Best for complex coding, refactoring, multi-file operations, "
            "and tasks requiring deep codebase understanding. Returns Claude Code's final response."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The coding task or question to send to Claude Code.",
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        f"Working directory for Claude Code to operate in "
                        f"(default: {CODEX_DEFAULT_WORKDIR})"
                    ),
                },
                "async": {
                    "type": "boolean",
                    "description": (
                        "When true, starts the task in the background and returns a job_id "
                        "immediately. Recommended for multi-minute tasks."
                    ),
                },
            },
            "required": ["task"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Background job ID (only when async=true). Use agent_job_status to check result."
                },
                "output": {
                    "type": "string",
                    "description": "Claude Code's final response text, or error message if the call failed."
                },
                "exit_code": {
                    "type": "integer",
                    "description": "0 on success, non-zero on error."
                }
            }
        },
    },
    {
        "name": "agent_job_status",
        "description": (
            "Checks the status of a background agent job started with async=true. "
            "Returns queued/running/succeeded/failed plus any final output when available."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "The job_id returned by codex_agent, gemini_agent, or claude_code_agent.",
                },
            },
            "required": ["job_id"],
        },
    },
    {
        "name": "agent_job_list",
        "description": (
            "Lists recent background agent jobs. "
            "Supports optional status filter and limit."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Optional status filter: queued, running, succeeded, failed",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max jobs to return (default 20, max 100).",
                },
            },
        },
    },
    {
        "name": "agent_job_cleanup",
        "description": (
            "Deletes expired background agent jobs from in-memory storage "
            "and returns how many records were removed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "smart_agent",
        "description": (
            "Runs a task through a fallback chain of local AI agents. "
            "Starts with Gemini for speed, then falls back to Codex, then Claude Code "
            "when quota limits, timeouts, or transient upstream failures occur. "
            "Use this as the default tool for local execution when the user wants the server "
            "to handle agent rotation automatically, especially for file edits, shell commands, "
            "or any task that may outlive a single HTTP request. Prefer async=true for remote clients."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task to execute with automatic fallback across agents.",
                },
                "working_dir": {
                    "type": "string",
                    "description": (
                        f"Working directory for the selected agent to operate in "
                        f"(default: {CODEX_DEFAULT_WORKDIR})"
                    ),
                },
                "async": {
                    "type": "boolean",
                    "description": (
                        "When true, starts the fallback workflow in the background and returns "
                        "a job_id immediately."
                    ),
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "notion_search",
        "description": (
            "Search pages and databases in Notion. Returns a list of matching pages "
            "with their titles, IDs, and URLs. Use this to find Notion content by keyword."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keyword to find in Notion pages and databases.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max number of results to return (default 10, max 20).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "notion_get_page",
        "description": (
            "Fetch the content of a specific Notion page by its page ID or URL. "
            "Returns the page title and all text blocks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_id": {
                    "type": "string",
                    "description": "Notion page ID (UUID format) or full Notion page URL.",
                },
            },
            "required": ["page_id"],
        },
    },
    {
        "name": "mmx_image_generate",
        "description": (
            "Generate images using MiniMax AI image-01 model. "
            "Returns image URLs or saved file paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Image description prompt."},
                "aspect_ratio": {"type": "string", "description": "Aspect ratio like 16:9, 1:1, 9:16."},
                "n": {"type": "integer", "description": "Number of images to generate (default 1)."},
                "out_dir": {"type": "string", "description": "Directory to save images."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "mmx_video_generate",
        "description": (
            "Generate videos using MiniMax AI Hailuo-2.3 model. "
            "This is async — set async=true to get a job_id immediately, "
            "or wait for the video to be generated and returned as a file path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Video description prompt."},
                "async": {"type": "boolean", "description": "Return job_id immediately without waiting."},
                "first_frame": {"type": "string", "description": "Path or URL to first frame image."},
                "download": {"type": "string", "description": "File path to save the video."},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "mmx_speech_synthesize",
        "description": (
            "Text-to-speech using MiniMax speech-2.8-hd model. "
            "Converts text to audio file (mp3 by default)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to synthesize (max 10k chars)."},
                "text_file": {"type": "string", "description": "Path to text file (use - for stdin)."},
                "voice": {"type": "string", "description": "Voice ID (default: English_expressive_narrator)."},
                "model": {"type": "string", "description": "Model: speech-2.8-hd, speech-2.6, or speech-02."},
                "speed": {"type": "number", "description": "Speed multiplier."},
                "format": {"type": "string", "description": "Audio format (default: mp3)."},
                "out": {"type": "string", "description": "Output file path."},
            },
            "required": ["text"],
        },
    },
    {
        "name": "mmx_music_generate",
        "description": (
            "Generate music using MiniMax music-2.5 model. "
            "Can create songs with vocals or instrumental music."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Music style/description prompt."},
                "lyrics": {"type": "string", "description": "Song lyrics with structure tags."},
                "vocals": {"type": "string", "description": "Vocal style description."},
                "genre": {"type": "string", "description": "Music genre."},
                "mood": {"type": "string", "description": "Mood or emotion."},
                "instruments": {"type": "string", "description": "Instruments to feature."},
                "bpm": {"type": "number", "description": "Exact tempo in BPM."},
                "instrumental": {"type": "boolean", "description": "Generate instrumental without vocals."},
                "out": {"type": "string", "description": "Output file path."},
            },
        },
    },
    {
        "name": "mmx_vision_describe",
        "description": (
            "Image understanding via MiniMax VL model. "
            "Describes or answers questions about an image."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Image path or URL."},
                "file_id": {"type": "string", "description": "Pre-uploaded file ID."},
                "prompt": {"type": "string", "description": "Question about the image."},
            },
            "required": ["image"],
        },
    },
    {
        "name": "mmx_search_query",
        "description": "Web search via MiniMax AI.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Search query."},
            },
            "required": ["q"],
        },
    },
    {
        "name": "mmx_text_chat",
        "description": (
            "Chat completion using MiniMax MiniMax-M2.7 model. "
            "Supports multi-turn conversation and system prompts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Message text. Prefix with role: to set role."},
                "system": {"type": "string", "description": "System prompt."},
                "model": {"type": "string", "description": "Model ID (default: MiniMax-M2.7)."},
                "max_tokens": {"type": "integer", "description": "Max tokens (default: 4096)."},
                "temperature": {"type": "number", "description": "Sampling temperature (0.0-1.0)."},
            },
            "required": ["message"],
        },
    },
    {
        "name": "mmx_quota_show",
        "description": "Display MiniMax Token Plan usage and remaining quotas.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ollama_agent",
        "description": (
            "Delegates a task to a local Ollama AI model (qwen3.5). "
            "Fast, runs locally, no API cost. "
            "Use for quick coding tasks, summarization, and general automation."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The task or instruction for Ollama to execute."},
                "model": {"type": "string", "description": "Model name (default: qwen3.5:latest)."},
                "working_dir": {"type": "string", "description": f"Working directory (default: {CODEX_DEFAULT_WORKDIR})"},
            },
            "required": ["task"],
        },
    },
    {
        "name": "ollama_list_models",
        "description": "List locally available Ollama models through the handcraft MCP.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "ollama_generate",
        "description": "Generate a completion from a local Ollama model through the handcraft MCP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Ollama model name."},
                "prompt": {"type": "string", "description": "Prompt text."},
                "system": {"type": "string", "description": "Optional system instruction."},
            },
            "required": ["model", "prompt"],
        },
    },
    {
        "name": "ollama_chat",
        "description": "Run a chat completion against a local Ollama model through the handcraft MCP.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Ollama model name."},
                "messages": {
                    "type": "array",
                    "description": "Chat message list.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {
                                "type": "string",
                                "enum": ["system", "user", "assistant", "tool"],
                            },
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
            },
            "required": ["model", "messages"],
        },
    },
    # ── 檔案系統工具 ──────────────────────────────────────────────────────────
    {
        "name": "fs_list",
        "description": "List directory contents with file sizes, types, and modification dates.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
                "show_hidden": {"type": "boolean", "description": "Include hidden files/folders (default: false)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_read",
        "description": "Read the contents of a file. Truncates at max_lines to avoid overloading context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "max_lines": {"type": "integer", "description": "Max lines to return (default: 200)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_write",
        "description": "Write or create a file. Can append to existing file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
                "append": {"type": "boolean", "description": "Append instead of overwrite (default: false)"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "fs_move",
        "description": "Move or rename a file or folder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Source path"},
                "dst": {"type": "string", "description": "Destination path"},
            },
            "required": ["src", "dst"],
        },
    },
    {
        "name": "fs_delete",
        "description": "Safely delete a file or folder by moving it to a trash folder (C:\\Users\\EdgarsTool\\.mcp-trash). NOT permanent — can be recovered manually.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File or folder path to delete (moved to trash)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "fs_search",
        "description": "Search for files by name pattern (glob) and optionally by content substring.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {"type": "string", "description": "Root directory to search in"},
                "pattern": {"type": "string", "description": "Filename glob pattern (e.g. '*.py', '*.md', default: '*')"},
                "search_content": {"type": "string", "description": "Optional substring to search inside file contents"},
                "max_results": {"type": "integer", "description": "Max results to return (default: 50)"},
            },
            "required": ["directory"],
        },
    },
    {
        "name": "fs_disk_info",
        "description": "Show disk usage for all drives (used/free/total space with visual bar).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    # ── 系統工具 ──────────────────────────────────────────────────────────────
    {
        "name": "sys_run",
        "description": "Run a PowerShell command on the local machine and return output. Timeout max 120s. Dangerous patterns are blocked.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "PowerShell command to execute"},
                "working_dir": {"type": "string", "description": "Working directory (default: user home)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30, max: 120)"},
            },
            "required": ["command"],
        },
    },
    {
        "name": "sys_info",
        "description": "Get system information: CPU, RAM usage, OS version.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "sys_processes",
        "description": "List running processes sorted by memory or CPU usage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of processes to return (default: 20)"},
                "sort_by": {"type": "string", "description": "Sort by: 'memory' (default), 'cpu', or 'name'"},
            },
        },
    },
    # ── Git 工具 ─────────────────────────────────────────────────────────────
    {
        "name": "git_status",
        "description": "Show git working tree status for a repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": f"Repo path (default: {CODEX_DEFAULT_WORKDIR})"},
            },
        },
    },
    {
        "name": "git_log",
        "description": "Show recent git commit history (one-line format).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repo path"},
                "limit": {"type": "integer", "description": "Number of commits (default: 10)"},
            },
        },
    },
    {
        "name": "git_diff",
        "description": "Show git diff summary (changed files and line counts).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repo path"},
                "staged": {"type": "boolean", "description": "Show staged diff (default: false = unstaged)"},
            },
        },
    },
    {
        "name": "git_commit",
        "description": "Stage files and create a git commit.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Repo path"},
                "message": {"type": "string", "description": "Commit message"},
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to stage (empty = git add -A for all changes)",
                },
            },
            "required": ["message"],
        },
    },
    # ── Playwright 瀏覽器工具 ─────────────────────────────────────────────────
    {
        "name": "browser_screenshot",
        "description": "Open a URL in headless Chromium, wait for load, save a screenshot PNG, and return the file path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to open"},
                "wait_ms": {"type": "integer", "description": "Extra wait after load in ms (default: 2000)"},
                "full_page": {"type": "boolean", "description": "Capture full page scroll height (default: false)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_get_text",
        "description": "Fetch a URL in headless Chromium and return the visible text content of the page (or a CSS selector).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to open"},
                "selector": {"type": "string", "description": "CSS selector to extract text from (default: body)"},
                "wait_ms": {"type": "integer", "description": "Extra wait after load in ms (default: 1000)"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_run_script",
        "description": "Navigate to a URL and run JavaScript, returning the result. Useful for scraping or checking page state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to open"},
                "script": {"type": "string", "description": "JavaScript to evaluate (return value is serialized to JSON)"},
                "wait_ms": {"type": "integer", "description": "Extra wait after load (default: 1000)"},
            },
            "required": ["url", "script"],
        },
    },
    # ── Obsidian Vault 工具 ───────────────────────────────────────────────────
    {
        "name": "vault_read",
        "description": "Read an Obsidian note by relative path (e.g. '00 Inbox/my-note.md').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside vault"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "vault_write",
        "description": "Create or overwrite an Obsidian note. Creates parent folders automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "Relative path inside vault"},
                "content": {"type": "string", "description": "Full markdown content"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "vault_append",
        "description": "Append text to an existing Obsidian note (adds a newline before appended content).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "Relative path inside vault"},
                "content": {"type": "string", "description": "Text to append"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "vault_list",
        "description": "List files and folders inside a vault directory.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative folder path (default: vault root)"},
            },
        },
    },
    {
        "name": "vault_search",
        "description": "Full-text search across all .md files in the vault. Returns matching file paths and context snippets.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string", "description": "Text to search for"},
                "max_results": {"type": "integer", "description": "Max results (default: 20)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "vault_delete",
        "description": "Delete a vault note (moves to vault .trash folder, recoverable from Obsidian).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path inside vault"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "vault_move",
        "description": "Move or rename a vault note.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "src": {"type": "string", "description": "Source relative path"},
                "dst": {"type": "string", "description": "Destination relative path"},
            },
            "required": ["src", "dst"],
        },
    },
    {
        "name": "vault_daily_note",
        "description": "Get or create today's daily note in 00 Inbox/Daily/YYYY-MM-DD.md with the Daily Notes template.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format (default: today)"},
            },
        },
    },
    {
        "name": "vault_recent",
        "description": "List the most recently modified notes in the vault.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit":  {"type": "integer", "description": "Number of notes (default: 15)"},
                "folder": {"type": "string",  "description": "Limit to a subfolder (optional)"},
            },
        },
    },
    {
        "name": "vault_tasks",
        "description": "Find all unchecked tasks (- [ ]) across the vault. Useful for a global TODO overview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Limit search to a subfolder (optional)"},
                "limit":  {"type": "integer", "description": "Max tasks to return (default: 50)"},
            },
        },
    },
    {
        "name": "vault_tags",
        "description": "List all tags used across the vault with their counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "vault_create_from_template",
        "description": "Create a new note from a vault template. Available templates: Daily Notes, Project, Learning Project, Research Clipping, Service Subscription, Meeting Notes, Weekly Review, Decision Record.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template": {"type": "string", "description": "Template name (e.g. 'Project', 'Meeting Notes')"},
                "title":    {"type": "string", "description": "Note title (used as filename and in content)"},
                "folder":   {"type": "string", "description": "Destination folder (default: 00 Inbox)"},
                "fields":   {"type": "object", "description": "Key-value pairs to fill in template variables"},
            },
            "required": ["template", "title"],
        },
    },
    {
        "name": "vault_sort_inbox",
        "description": (
            "自動掃描 Obsidian Vault 的 00 Inbox，判斷每個散落筆記的分類，"
            "批次搬移到正確的 PARA 資料夾（01 Projects / 02 Areas / 03 Resources / 04 Archive）。"
            "不會動 Daily Notes 子資料夾和 Don't Touch 子資料夾。"
            "完成後回傳搬移清單。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "dry_run": {
                    "type": "boolean",
                    "description": "若為 true，只列出分類結果但不實際搬移（預設 false）",
                },
            },
        },
    },
    # ── TrackTW 物流查詢 ─────────────────────────────────────────────────────
    {
        "name": "tracktw_carriers",
        "description": "List available TrackTW logistics carriers. Use this when a store/carrier keyword cannot be resolved.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optional carrier/store keyword filter, e.g. 黑貓, 7-Eleven, 全家.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max carriers to return (default 50, max 200).",
                },
            },
        },
    },
    {
        "name": "tracktw_package_status",
        "description": (
            "Query TrackTW by logistics carrier/store keyword and tracking number. "
            "Returns the current stage, transition-oriented timeline, "
            "estimated arrival wording, and can export a CSV/XLSX report."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "carrier_name": {
                    "type": "string",
                    "description": "Logistics carrier or store keyword, e.g. 黑貓, 7-Eleven, 全家.",
                },
                "tracking_number": {
                    "type": "string",
                    "description": "Package tracking number.",
                },
                "export_report": {
                    "type": "boolean",
                    "description": "When true, write a spreadsheet report file (default false).",
                },
                "report_format": {
                    "type": "string",
                    "description": "Report format: xlsx, csv, or both (default xlsx).",
                },
                "output_dir": {
                    "type": "string",
                    "description": f"Directory for report files (default: {REPORTS_DIR}).",
                },
            },
            "required": ["carrier_name", "tracking_number"],
        },
    },
    # ── 免費圖片生成（Pollinations.AI，不需 API key）─────────────────────────
    {
        "name": "image_generate_free",
        "description": (
            "Generate an image for FREE using Pollinations.AI (no API key needed). "
            "Saves PNG to .screenshots/ and returns the file path. "
            "Models: flux (default, best quality), turbo (fast), gptimage."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Image description prompt"},
                "width":  {"type": "integer", "description": "Width in px (default: 1024)"},
                "height": {"type": "integer", "description": "Height in px (default: 1024)"},
                "model":  {"type": "string",  "description": "Model: flux (default) | turbo | gptimage"},
                "seed":   {"type": "integer", "description": "Seed for reproducibility (optional)"},
            },
            "required": ["prompt"],
        },
    },
    # ── Web Search ────────────────────────────────────────────────────────────
    {
        "name": "web_search",
        "description": "Search the web using Perplexity AI and return a summarized answer with sources.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    # ── Linear 工具 ───────────────────────────────────────────────────────────
    {
        "name": "linear_issues",
        "description": "List Linear issues. Filter by state name (e.g. 'In Progress', 'Todo', 'Done').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "description": "Filter by state name (optional)"},
                "limit": {"type": "integer", "description": "Number of issues (default: 10)"},
                "assignee_me": {"type": "boolean", "description": "Only show issues assigned to me (default: false)"},
            },
        },
    },
    {
        "name": "linear_create_issue",
        "description": "Create a new Linear issue.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue title"},
                "description": {"type": "string", "description": "Issue description (markdown)"},
                "team_name": {"type": "string", "description": "Team name (default: first team found)"},
                "priority": {"type": "integer", "description": "Priority 0=none 1=urgent 2=high 3=medium 4=low (default: 3)"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "linear_update_issue",
        "description": "Update a Linear issue state or add a comment.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "Issue ID (e.g. 'WHO-123')"},
                "state": {"type": "string", "description": "New state name (e.g. 'Done', 'In Progress')"},
                "comment": {"type": "string", "description": "Comment to add"},
            },
            "required": ["issue_id"],
        },
    },
    # ── Warp Oz Cloud Agents ───────────────────────────────────────────────────
    {
        "name": "warp_agent_runs_list",
        "description": "List recent Warp Oz cloud agent runs (Warp terminal cloud agents API).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max runs to return (default: 10)"},
            },
        },
    },
    {
        "name": "warp_agent_run_status",
        "description": "Get status and details for a single Warp Oz agent run by run_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Warp agent run ID"},
            },
            "required": ["run_id"],
        },
    },
    {
        "name": "warp_agent_run_create",
        "description": "Start a new Warp Oz cloud agent run with a prompt (requires environment_id).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Task instruction for the agent"},
                "environment_id": {"type": "string", "description": "Oz cloud environment ID (from oz environment list)"},
                "title": {"type": "string", "description": "Optional display title for the run"},
            },
            "required": ["prompt", "environment_id"],
        },
    },
    # ── Cursor Cloud Agents API ─────────────────────────────────────────────────
    {
        "name": "cursor_agents_list",
        "description": "List Cursor Cloud Agents (background agents) for the authenticated account.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max agents to return (default: 10)"},
            },
        },
    },
    {
        "name": "cursor_agent_get",
        "description": "Get a Cursor Cloud Agent by agent ID, including latest run metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Cursor agent ID (e.g. bc-...)"},
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "cursor_agent_create",
        "description": "Create a Cursor Cloud Agent and enqueue its initial run with a prompt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Task instruction for the agent"},
                "repo_url": {"type": "string", "description": "GitHub repo URL (optional, e.g. https://github.com/org/repo)"},
                "branch": {"type": "string", "description": "Starting branch or ref (optional)"},
                "name": {"type": "string", "description": "Optional display name for the agent"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "cursor_agent_run_status",
        "description": "Get status for a specific Cursor agent run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "Cursor agent ID"},
                "run_id": {"type": "string", "description": "Run ID from agent create or list"},
            },
            "required": ["agent_id", "run_id"],
        },
    },
    # ── Factory.ai (Droid platform) ─────────────────────────────────────────────
    {
        "name": "factory_sessions_list",
        "description": "List Factory Droid sessions (factory.ai). May require org feature flag.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max sessions (default: 10)"},
            },
        },
    },
    {
        "name": "factory_session_get",
        "description": "Get a Factory Droid session by session ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Factory session ID"},
            },
            "required": ["session_id"],
        },
    },
    {
        "name": "factory_computers_list",
        "description": "List Factory Droid Computers (persistent dev environments).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "factory_readiness_reports",
        "description": "List Factory agent readiness / maturity reports for repositories.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max reports (default: 10)"},
                "repo_id": {"type": "string", "description": "Filter by repository ID (optional)"},
            },
        },
    },
]

READ_ONLY_TOOL_NAMES = {
    "echo",
    "agent_job_status",
    "agent_job_list",
    "notion_search",
    "notion_get_page",
    "mmx_vision_describe",
    "mmx_search_query",
    "mmx_text_chat",
    "mmx_quota_show",
    "fs_list",
    "fs_read",
    "fs_search",
    "fs_disk_info",
    "sys_info",
    "sys_processes",
    "git_status",
    "git_log",
    "git_diff",
    "browser_get_text",
    "browser_run_script",
    "vault_read",
    "vault_list",
    "vault_search",
    "vault_recent",
    "vault_tasks",
    "vault_tags",
    "tracktw_carriers",
    "tracktw_package_status",
    "web_search",
    "linear_issues",
    "warp_agent_runs_list",
    "warp_agent_run_status",
    "cursor_agents_list",
    "cursor_agent_get",
    "cursor_agent_run_status",
    "factory_sessions_list",
    "factory_session_get",
    "factory_computers_list",
    "factory_readiness_reports",
}

DESTRUCTIVE_TOOL_NAMES = {
    "fs_write",
    "fs_delete",
    "vault_write",
    "vault_delete",
    "vault_sort_inbox",
    "git_commit",
    "linear_update_issue",
    "warp_agent_run_create",
    "cursor_agent_create",
}

DEFAULT_TEXT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "content": {
            "type": "array",
            "description": "MCP text content blocks returned by the tool.",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["text"]},
                    "text": {"type": "string"},
                },
                "required": ["type", "text"],
            },
        },
        "isError": {
            "type": "boolean",
            "description": "True when the tool returned an error payload.",
        },
    },
    "required": ["content"],
}


def _tool_impact_annotations(tool_name: str) -> dict:
    read_only = tool_name in READ_ONLY_TOOL_NAMES
    destructive = tool_name in DESTRUCTIVE_TOOL_NAMES
    return {
        "readOnlyHint": read_only,
        "openWorldHint": not read_only,
        "destructiveHint": destructive,
    }


def _normalize_tool_descriptor(tool: dict) -> dict:
    descriptor = dict(tool)
    name = str(descriptor.get("name") or "")
    descriptor.setdefault("title", name.replace("_", " ").title())
    descriptor.setdefault("annotations", _tool_impact_annotations(name))
    descriptor.setdefault("securitySchemes", [{"type": "oauth2", "scopes": [OAUTH_SCOPE]}])
    descriptor.setdefault("outputSchema", DEFAULT_TEXT_OUTPUT_SCHEMA)
    meta = dict(descriptor.get("_meta") or {})
    meta.setdefault("securitySchemes", descriptor["securitySchemes"])
    descriptor["_meta"] = meta
    return descriptor


TOOLS = [_normalize_tool_descriptor(tool) for tool in TOOLS]

# ── Origin 白名單（防 DNS rebinding，spec 強制要求）────────────────────────────
# 允許 localhost / 127.0.0.1 任意 port，供本地開發 + MCP Inspector 使用。
# Cloudflare Tunnel 接入後，瀏覽器 origin 會是 tunnel domain，需另行加入。
ALLOWED_HOSTNAMES = {
    "localhost",
    "127.0.0.1",
    "mcp.whoasked.vip",
    "mcp.edgars.tools",
    "chatgpt.com",
    "chat.openai.com",
    # ChatGPT MCP connector may POST with these Origins after OAuth (CIMD flow).
    "openai.com",
    "connector.openai.com",
}


# ─── 共用工具 ─────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"[MCP-HTTP] {msg}", file=sys.stderr, flush=True)


def make_response(req_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def make_error(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def make_tool_text_response(text: str, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": text}],
        "isError": is_error,
    }


def make_tool_json_response(data: dict, *, is_error: bool = False) -> dict:
    return {
        "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
        "structuredContent": data,
        "isError": is_error,
    }


class SafeMcpWriteError(RuntimeError):
    pass


class LinearMcpError(RuntimeError):
    pass


class WarpMcpError(RuntimeError):
    pass


class CursorMcpError(RuntimeError):
    pass


class FactoryMcpError(RuntimeError):
    pass


class CloudflareAccessAuthError(RuntimeError):
    pass


def format_safe_mcp_failure(action: str, target: str, reason: str) -> str:
    return f"[BLOCKED] {action} failed\nTarget: {target}\nReason: {reason}"


def build_mcp_resource_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{MCP_PATH}"


def build_oauth_protected_resource_metadata_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/.well-known/oauth-protected-resource{MCP_PATH}"


def make_www_authenticate_header(base_url: str, *, error: str | None = None, description: str | None = None) -> str:
    parts = [
        f'resource_metadata="{build_oauth_protected_resource_metadata_url(base_url)}"',
        f'scope="{OAUTH_SCOPE}"',
    ]
    if error:
        parts.append(f'error="{error}"')
    if description:
        parts.append(f'error_description="{description}"')
    return "Bearer " + ", ".join(parts)


def make_webhook_response(event_type: str, accepted: bool = True) -> dict:
    return {
        "ok": accepted,
        "type": event_type,
        "service": f"handcraft-{event_type}-webhook",
    }


def parse_request_params(raw: bytes, content_type: str) -> dict:
    if "application/json" in content_type:
        try:
            data = json.loads(raw.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {k: v[0] for k, v in urllib.parse.parse_qs(raw.decode("utf-8")).items()}


def oauth_error(error: str, description: str = "") -> dict:
    payload = {"error": error}
    if description:
        payload["error_description"] = description
    return payload


def is_safe_oauth_redirect_uri(redirect_uri: str) -> bool:
    parsed = urllib.parse.urlparse(redirect_uri)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        return True
    return False


def is_https_url_client_id(client_id: str) -> bool:
    """True when client_id is an HTTPS URL (CIMD per MCP 2025-11-25).

    Query strings and fragments are allowed — ChatGPT per-connector metadata URLs
    use client_id like https://chatgpt.com/oauth/{id}/client.json?token_endpoint_auth_method=none
    and the metadata document's client_id must match that URL exactly.
    """
    parsed = urllib.parse.urlparse(client_id)
    return parsed.scheme == "https" and bool(parsed.netloc)


def is_safe_cimd_fetch_target(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "::1"}:
        return False
    if host.endswith(".local") or host.endswith(".internal"):
        return False
    if re.match(r"^(10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.)", host):
        return False
    return True


def _cimd_cache_get(client_id_url: str) -> dict | None:
    now = time.time()
    with OAUTH_CIMD_CACHE_LOCK:
        entry = OAUTH_CIMD_CACHE.get(client_id_url)
        if not entry:
            return None
        if entry.get("expires_at", 0) < now:
            OAUTH_CIMD_CACHE.pop(client_id_url, None)
            return None
        client = entry.get("client")
        return dict(client) if isinstance(client, dict) else None


def _cimd_cache_put(client_id_url: str, client: dict, *, max_age_seconds: int | None = None) -> None:
    ttl = max_age_seconds if max_age_seconds is not None else OAUTH_CIMD_CACHE_TTL_SECONDS
    ttl = max(60, min(int(ttl), OAUTH_CIMD_CACHE_TTL_SECONDS))
    with OAUTH_CIMD_CACHE_LOCK:
        OAUTH_CIMD_CACHE[client_id_url] = {
            "client": dict(client),
            "expires_at": time.time() + ttl,
        }


def _parse_cimd_http_cache_control(cache_control: str) -> int | None:
    for part in cache_control.split(","):
        piece = part.strip().lower()
        if piece.startswith("max-age="):
            try:
                return int(piece.split("=", 1)[1].strip())
            except ValueError:
                return None
    return None


def is_auth_edgars_chatgpt_cimd_url(client_id_url: str) -> bool:
    return client_id_url.rstrip("/") == OAUTH_AUTH_CHATGPT_CIMD_URL.rstrip("/")


def auth_edgars_chatgpt_cimd_bootstrap_metadata() -> dict:
    """Local bootstrap for auth.edgars.tools ChatGPT CIMD when fetch is unavailable."""
    return {
        "client_id": OAUTH_AUTH_CHATGPT_CIMD_URL,
        "client_name": "EDGAR'S Tools ChatGPT Connector",
        "grant_types": ["authorization_code"],
        "response_types": ["code"],
        "scope": "mcp",
        "token_endpoint_auth_method": "none",
        "application_type": "web",
        "client_uri": "https://www.edgars.tools/",
        "logo_uri": "https://www.edgars.tools/assets/logo-brand.png",
        "tos_uri": "https://www.edgars.tools/terms.html",
        "policy_uri": "https://www.edgars.tools/privacy.html",
        "redirect_uris": [CHATGPT_CONNECTOR_REDIRECT_PREFIX],
    }


def is_chatgpt_connector_redirect_uri(redirect_uri: str) -> bool:
    return redirect_uri.startswith(CHATGPT_CONNECTOR_REDIRECT_PREFIX)


def oauth_redirect_uri_matches_registered(client: dict, redirect_uri: str) -> bool:
    registered = client.get("redirect_uris") or []
    if redirect_uri in registered:
        return True
    for entry in registered:
        if isinstance(entry, str) and entry.endswith("/") and redirect_uri.startswith(entry):
            return True
    for prefix in client.get("redirect_uri_prefixes") or []:
        if isinstance(prefix, str) and redirect_uri.startswith(prefix):
            return True
    return False


def validate_cimd_metadata_document(client_id_url: str, metadata: dict) -> tuple[dict | None, str]:
    if not isinstance(metadata, dict):
        return None, "metadata document must be a JSON object"
    doc_client_id = str(metadata.get("client_id") or "").strip()
    if doc_client_id != client_id_url:
        return None, "client_id in metadata must exactly match the metadata URL"
    client_name = metadata.get("client_name")
    if not isinstance(client_name, str) or not client_name.strip():
        return None, "client_name is required in metadata document"
    redirect_uris = metadata.get("redirect_uris")
    if not isinstance(redirect_uris, list) or not redirect_uris:
        return None, "redirect_uris must be a non-empty array in metadata document"
    if not all(isinstance(uri, str) and is_safe_oauth_redirect_uri(uri) for uri in redirect_uris):
        return None, "redirect_uris must contain safe HTTPS or localhost HTTP URIs"
    auth_method = str(metadata.get("token_endpoint_auth_method") or "none").strip() or "none"
    if auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
        return None, "unsupported token_endpoint_auth_method in metadata document"
    client = {
        "client_id": client_id_url,
        "client_name": client_name.strip(),
        "client_secret": "",
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": auth_method,
        "source": "cimd",
    }
    if is_auth_edgars_chatgpt_cimd_url(client_id_url):
        if auth_method != "none":
            return None, "auth.edgars.tools ChatGPT CIMD must use token_endpoint_auth_method none"
        client["redirect_uri_prefixes"] = [CHATGPT_CONNECTOR_REDIRECT_PREFIX]
        client["chatgpt_public_client"] = True
    return client, ""


def fetch_cimd_document(client_id_url: str) -> tuple[dict | None, dict[str, str], str]:
    """Fetch and validate a Client ID Metadata Document. Returns (metadata, response_headers, error)."""
    if not is_https_url_client_id(client_id_url):
        return None, {}, "client_id must be an HTTPS URL"
    if not is_safe_cimd_fetch_target(client_id_url):
        return None, {}, "metadata URL is not allowed"

    req = urllib.request.Request(
        client_id_url,
        headers={"Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=OAUTH_CIMD_FETCH_TIMEOUT_SECONDS) as response:
            headers = {k.lower(): v for k, v in response.headers.items()}
            raw = response.read(OAUTH_CIMD_MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return None, {}, f"failed to fetch metadata document: HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return None, {}, f"failed to fetch metadata document: {exc.reason}"
    except Exception as exc:
        return None, {}, f"failed to fetch metadata document: {exc}"

    if len(raw) > OAUTH_CIMD_MAX_BYTES:
        return None, headers, "metadata document exceeds size limit"
    try:
        metadata = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, headers, "metadata document is not valid JSON"
    return metadata, headers, ""


def resolve_cimd_oauth_client(client_id_url: str) -> dict | None:
    cached = _cimd_cache_get(client_id_url)
    if cached:
        return cached

    metadata, response_headers, fetch_error = fetch_cimd_document(client_id_url)
    if fetch_error or not isinstance(metadata, dict):
        if is_auth_edgars_chatgpt_cimd_url(client_id_url):
            metadata = auth_edgars_chatgpt_cimd_bootstrap_metadata()
            response_headers = {}
        else:
            return None
    client, validation_error = validate_cimd_metadata_document(client_id_url, metadata)
    if validation_error or not client:
        return None

    max_age = _parse_cimd_http_cache_control(response_headers.get("cache-control", ""))
    if max_age is None:
        max_age = OAUTH_CIMD_CACHE_TTL_SECONDS
    _cimd_cache_put(client_id_url, client, max_age_seconds=max_age)
    return dict(client)


def build_oauth_authorization_server_metadata(base_url: str) -> dict:
    base_url = base_url.rstrip("/")
    metadata = {
        "issuer": base_url,
        "authorization_endpoint": f"{base_url}/authorize",
        "token_endpoint": f"{base_url}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "client_id_metadata_document_supported": True,
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
        "token_endpoint_auth_signing_alg_values_supported": [],
        "revocation_endpoint_auth_methods_supported": ["none"],
        "scopes_supported": OAUTH_OIDC_SCOPES,
        "subject_types_supported": ["public"],
    }
    if OAUTH_DCR_ENABLED:
        metadata["registration_endpoint"] = f"{base_url}/register"
    return metadata


def build_openid_configuration_metadata(base_url: str) -> dict:
    metadata = build_oauth_authorization_server_metadata(base_url)
    metadata.update({
        "userinfo_endpoint": f"{base_url.rstrip('/')}/userinfo",
        "id_token_signing_alg_values_supported": [],
        "response_modes_supported": ["query"],
        "claims_supported": ["sub", "name", "email"],
    })
    return metadata


def get_oauth_client(client_id: str) -> dict | None:
    if not client_id:
        return None
    with OAUTH_CLIENTS_LOCK:
        client = OAUTH_CLIENTS.get(client_id)
        if client:
            return dict(client)
    if client_id == OAUTH_STATIC_CLIENT_ID:
        return {
            "client_id": OAUTH_STATIC_CLIENT_ID,
            "client_name": CONNECTOR_DISPLAY_NAME,
            "client_secret": OAUTH_STATIC_CLIENT_SECRET,
            "redirect_uris": [],
            "allow_dynamic_redirect": True,
            "token_endpoint_auth_method": "client_secret_post",
            "source": "pre_registered",
        }
    if is_https_url_client_id(client_id):
        return resolve_cimd_oauth_client(client_id)
    return None


def oauth_redirect_uri_allowed(client: dict, redirect_uri: str) -> bool:
    if not is_safe_oauth_redirect_uri(redirect_uri):
        return False
    if client.get("chatgpt_public_client") and not is_chatgpt_connector_redirect_uri(redirect_uri):
        return False
    if client.get("allow_dynamic_redirect"):
        return True
    return oauth_redirect_uri_matches_registered(client, redirect_uri)


def pkce_s256_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def pkce_verifier_matches(verifier: str, challenge: str, method: str) -> bool:
    if method != "S256" or not verifier or not challenge:
        return False
    try:
        calculated = pkce_s256_challenge(verifier)
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(calculated, challenge)


def parse_basic_client_credentials(auth_header: str) -> tuple[str, str] | None:
    if not auth_header.startswith("Basic "):
        return None
    try:
        raw = base64.b64decode(auth_header.removeprefix("Basic ").strip()).decode("utf-8")
    except Exception:
        return None
    client_id, sep, client_secret = raw.partition(":")
    if not sep:
        return None
    return urllib.parse.unquote_plus(client_id), urllib.parse.unquote_plus(client_secret)


def oauth_token_exchange_skips_client_secret(
    client: dict,
    params: dict,
    *,
    code_entry: dict | None,
) -> bool:
    """Public/PKCE token exchanges may omit client_secret (auth method 'none')."""
    if params.get("code_verifier"):
        return True
    if code_entry and code_entry.get("code_challenge"):
        return True
    return False


def oauth_client_secret_matches(client: dict, params: dict, auth_header: str) -> bool:
    expected = str(client.get("client_secret") or "")
    if not expected:
        return True

    basic_credentials = parse_basic_client_credentials(auth_header)
    if basic_credentials:
        basic_client_id, basic_secret = basic_credentials
        return (
            hmac.compare_digest(basic_client_id, str(client.get("client_id") or ""))
            and hmac.compare_digest(basic_secret, expected)
        )

    supplied = str(params.get("client_secret") or "")
    return hmac.compare_digest(supplied, expected)


def issue_oauth_access_token(client_id: str, scope: str) -> tuple[str, int]:
    token = secrets.token_urlsafe(48)
    now = time.time()
    with OAUTH_TOKENS_LOCK:
        OAUTH_ACCESS_TOKENS[token] = {
            "client_id": client_id,
            "scope": scope or "mcp",
            "issued_at": now,
            "expires_at": now + OAUTH_ACCESS_TOKEN_TTL_SECONDS,
        }
    return token, OAUTH_ACCESS_TOKEN_TTL_SECONDS


def oauth_access_token_is_valid(token: str) -> bool:
    if not token:
        return False
    now = time.time()
    with OAUTH_TOKENS_LOCK:
        entry = OAUTH_ACCESS_TOKENS.get(token)
        if not entry:
            return False
        if entry.get("expires_at", 0) < now:
            OAUTH_ACCESS_TOKENS.pop(token, None)
            return False
        return True


def get_cloudflare_access_jwk_client(jwks_url: str):
    if PyJWKClient is None:
        raise CloudflareAccessAuthError(
            "PyJWT with PyJWKClient support is required when Cloudflare Access mode is enabled."
        )
    with CLOUDFLARE_ACCESS_JWKS_LOCK:
        client = CLOUDFLARE_ACCESS_JWKS_CLIENTS.get(jwks_url)
        if client is None:
            client = PyJWKClient(jwks_url)
            CLOUDFLARE_ACCESS_JWKS_CLIENTS[jwks_url] = client
        return client


def verify_cloudflare_access_jwt(token: str, config: HandcraftServerConfig) -> dict:
    if not token:
        raise CloudflareAccessAuthError("Missing Cf-Access-Jwt-Assertion header.")
    if not config.cloudflare_access_enabled:
        raise CloudflareAccessAuthError("Cloudflare Access mode is not enabled for this server.")
    if jwt is None:
        raise CloudflareAccessAuthError("PyJWT is required to verify Cloudflare Access JWTs.")

    try:
        jwk_client = get_cloudflare_access_jwk_client(config.cloudflare_access_jwks_url)
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=config.cloudflare_access_aud,
            issuer=config.cloudflare_access_issuer,
        )
    except InvalidTokenError as exc:
        raise CloudflareAccessAuthError(f"Cloudflare Access JWT invalid: {exc}") from exc
    except CloudflareAccessAuthError:
        raise
    except Exception as exc:
        raise CloudflareAccessAuthError(f"Cloudflare Access JWT verification failed: {exc}") from exc

    return claims if isinstance(claims, dict) else {}


def bearer_token_is_authorized(token: str, static_token: str) -> bool:
    if static_token and hmac.compare_digest(token, static_token):
        return True
    return oauth_access_token_is_valid(token)


def run_agent_command(
    command: list[str],
    cwd: str,
    *,
    env_overrides: dict[str, str | None] | None = None,
) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_overrides:
        for key, value in env_overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value

    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=AGENT_TIMEOUT_SECONDS,
        cwd=cwd,
        env=env,
        shell=False,
    )


def finalize_agent_output(
    result: subprocess.CompletedProcess,
    *,
    stdout_text: str = "",
    fallback_label: str,
) -> tuple[str, bool]:
    stdout_text = stdout_text.strip() if stdout_text else ""
    stderr_text = (result.stderr or "").strip()

    output = stdout_text or (result.stdout or "").strip()

    if result.returncode != 0:
        sections = []
        if stderr_text:
            sections.append(f"[stderr]\n{stderr_text}")
        if output:
            sections.append(f"[stdout]\n{output}")
        output = "\n".join(sections).strip()

    if not output:
        output = f"{fallback_label} exited with code {result.returncode} (no output)"

    return output, result.returncode != 0


def create_job(tool_name: str, task: str, working_dir: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = time.time()
    with JOBS_LOCK:
        JOBS[job_id] = {
            "job_id": job_id,
            "tool": tool_name,
            "task": task,
            "working_dir": working_dir,
            "status": "queued",
            "created_at": now,
            "updated_at": now,
            "expires_at": now + DEFAULT_JOB_RETENTION_SECONDS,
            "output": "",
            "is_error": False,
        }
    return job_id


def update_job(job_id: str, **fields) -> None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = time.time()


def get_job(job_id: str) -> dict | None:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


def cleanup_expired_jobs() -> int:
    now = time.time()
    with JOBS_LOCK:
        expired_ids = [job_id for job_id, job in JOBS.items() if job.get("expires_at", now) < now]
        for job_id in expired_ids:
            JOBS.pop(job_id, None)
    return len(expired_ids)


def list_jobs(*, status: str | None = None, limit: int = 20) -> list[dict]:
    if limit <= 0:
        limit = 20
    limit = min(limit, 100)

    with JOBS_LOCK:
        jobs = [dict(job) for job in JOBS.values()]

    if status:
        jobs = [job for job in jobs if job.get("status") == status]

    jobs.sort(key=lambda item: item.get("created_at", 0), reverse=True)
    return jobs[:limit]


def build_job_status_text(job: dict) -> str:
    lines = [
        f"job_id: {job['job_id']}",
        f"tool: {job['tool']}",
        f"status: {job['status']}",
        f"working_dir: {job['working_dir']}",
    ]
    attempts = job.get("attempts") or []
    if attempts:
        lines.append("attempts:")
        for attempt in attempts:
            line = f"- {attempt.get('tool', 'unknown')}: {attempt.get('status', 'unknown')}"
            reason = (attempt.get("reason") or "").strip()
            if reason:
                line += f" ({reason})"
            lines.append(line)
    output = (job.get("output") or "").strip()
    if output:
        lines.extend(["output:", output])
    return "\n".join(lines)


def start_background_job(
    tool_name: str,
    task: str,
    working_dir: str,
    runner,
) -> str:
    job_id = create_job(tool_name, task, working_dir)

    def _worker() -> None:
        update_job(job_id, status="running")
        try:
            result = runner(task, working_dir)
            attempts = None
            if isinstance(result, tuple) and len(result) == 3:
                output, is_error, attempts = result
            else:
                output, is_error = result

            fields = {
                "status": "failed" if is_error else "succeeded",
                "output": output,
                "is_error": is_error,
            }
            if attempts is not None:
                fields["attempts"] = attempts
            update_job(job_id, **fields)
        except Exception as exc:
            update_job(
                job_id,
                status="failed",
                output=f"{tool_name} background job failed: {exc}",
                is_error=True,
            )

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return job_id


def maybe_start_async_job(req_id, arguments: dict, tool_name: str, runner):
    task = arguments.get("task", "").strip()
    working_dir = arguments.get("working_dir", CODEX_DEFAULT_WORKDIR)

    if not task:
        return None, make_response(req_id, make_tool_text_response("Error: task is required", is_error=True))

    if arguments.get("async") is not True:
        return (task, working_dir), None

    job_id = start_background_job(tool_name, task, working_dir, runner)
    log(f"{tool_name}: started background job job_id={job_id} workdir={working_dir!r}")
    return None, make_response(
        req_id,
        make_tool_text_response(
            "\n".join([
                f"{tool_name} started in background.",
                f"JOB_ID={job_id}",
                f"job_id: {job_id}",
                "Use agent_job_status with this job_id to check progress and fetch the final output.",
            ])
        ),
    )


def run_codex_task(task: str, working_dir: str) -> tuple[str, bool]:
    log(f"codex_agent: task={task!r} workdir={working_dir!r}")

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="codex_out_")
    os.close(tmp_fd)

    try:
        result = run_agent_command(
            [
                "cmd.exe",
                "/c",
                CODEX_CMD,
                "exec",
                "--full-auto",
                "--ephemeral",
                "--skip-git-repo-check",
                "-C", working_dir,
                "-o", tmp_path,
                task,
            ],
            cwd=working_dir,
        )
        log(f"codex_agent: exit_code={result.returncode}")

        output = ""
        try:
            with open(tmp_path, "r", encoding="utf-8") as f:
                output = f.read().strip()
        except Exception:
            pass

        return finalize_agent_output(
            result,
            stdout_text=output,
            fallback_label="Codex",
        )
    except subprocess.TimeoutExpired:
        return f"codex_agent timed out after {AGENT_TIMEOUT_SECONDS} seconds", True
    except Exception as exc:
        return f"Failed to run Codex: {exc}", True
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def run_gemini_task(task: str, working_dir: str) -> tuple[str, bool]:
    log(f"gemini_agent: task={task!r} workdir={working_dir!r}")

    try:
        result = run_agent_command(
            ["cmd.exe", "/c", GEMINI_CMD, "-p", task],
            cwd=working_dir,
        )
        log(f"gemini_agent: exit_code={result.returncode}")

        return finalize_agent_output(
            result,
            fallback_label="Gemini",
        )
    except subprocess.TimeoutExpired:
        return f"gemini_agent timed out after {AGENT_TIMEOUT_SECONDS} seconds", True
    except FileNotFoundError:
        return f"Error: gemini command not found at {GEMINI_CMD}", True
    except Exception as exc:
        return f"Failed to run Gemini: {exc}", True


def run_claude_code_task(task: str, working_dir: str) -> tuple[str, bool]:
    log(f"claude_code_agent: task={task!r} workdir={working_dir!r}")

    try:
        result = run_agent_command(
            ["cmd.exe", "/c", CLAUDE_CMD, "-p", task, "--output-format", "text"],
            cwd=working_dir,
            # Force Claude Code to use the locally logged-in first-party account.
            # Doppler or shell-level Anthropic API settings can otherwise override
            # OAuth and make claude_code_agent fail with "Invalid API key".
            env_overrides={
                "ANTHROPIC_AUTH_TOKEN": None,
                "ANTHROPIC_API_KEY": None,
                "ANTHROPIC_BASE_URL": None,
                "ANTHROPIC_MODEL": None,
                "ANTHROPIC_SMALL_FAST_MODEL": None,
                "ANTHROPIC_DEFAULT_SONNET_MODEL": None,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": None,
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": None,
            },
        )
        log(f"claude_code_agent: exit_code={result.returncode}")

        return finalize_agent_output(
            result,
            fallback_label="Claude Code",
        )
    except subprocess.TimeoutExpired:
        return f"claude_code_agent timed out after {AGENT_TIMEOUT_SECONDS} seconds", True
    except FileNotFoundError:
        return f"Error: claude command not found at {CLAUDE_CMD}", True
    except Exception as exc:
        return f"Failed to run Claude Code: {exc}", True


def summarize_error_reason(output: str) -> str:
    lowered = (output or "").lower()
    if "quota exceeded" in lowered or "terminalquotaerror" in lowered or "retry in" in lowered:
        return "quota_exceeded"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    if "429" in lowered:
        return "rate_limited"
    if "connection aborted" in lowered or "context canceled" in lowered:
        return "connection_aborted"
    if "internal error" in lowered or "unexpected critical error" in lowered:
        return "upstream_error"
    return "error"


def should_fallback(tool_name: str, output: str, is_error: bool) -> bool:
    if not is_error:
        return False
    reason = summarize_error_reason(output)
    if tool_name == "gemini_agent":
        return reason in {"quota_exceeded", "timeout", "rate_limited", "connection_aborted", "upstream_error"}
    if tool_name == "codex_agent":
        return reason in {"timeout", "connection_aborted", "upstream_error"}
    return False


def run_smart_agent(task: str, working_dir: str) -> tuple[str, bool, list[dict]]:
    attempts = []
    runners = [
        ("gemini_agent", run_gemini_task),
        ("codex_agent", run_codex_task),
        ("claude_code_agent", run_claude_code_task),
    ]

    for tool_name, runner in runners:
        output, is_error = runner(task, working_dir)
        reason = "" if not is_error else summarize_error_reason(output)
        attempts.append({
            "tool": tool_name,
            "status": "failed" if is_error else "succeeded",
            "reason": reason,
        })
        if not is_error:
            return output, False, attempts
        if not should_fallback(tool_name, output, is_error):
            return output, True, attempts

    return output, True, attempts


# ─── Request Handlers（與 stdio 版邏輯相同，改為 return 而非 send）────────────

def handle_initialize(req_id, params: dict) -> dict:
    client_version = params.get("protocolVersion", PROTOCOL_VERSION)
    log(f"initialize: client protocolVersion={client_version}")
    return make_response(req_id, {
        "protocolVersion": client_version,
        "capabilities": {"tools": {}},
        "serverInfo": SERVER_INFO,
    })


def handle_ping(req_id, params: dict) -> dict:
    log("ping")
    return make_response(req_id, {})


def handle_tools_list(req_id, params: dict) -> dict:
    log(f"tools/list: returning {len(TOOLS)} tool(s)")
    return make_response(req_id, {"tools": TOOLS})


def handle_tools_call(req_id, params: dict) -> dict:
    name = params.get("name")
    arguments = params.get("arguments", {})
    cleanup_expired_jobs()
    log(f"tools/call: name={name} arguments={arguments}")

    if name == "echo":
        message = arguments.get("message", "")
        return make_response(req_id, make_tool_text_response(f"echo: {message}"))

    if name == "codex_agent":
        return handle_codex_agent(req_id, arguments)

    if name == "gemini_agent":
        return handle_gemini_agent(req_id, arguments)

    if name == "claude_code_agent":
        return handle_claude_code_agent(req_id, arguments)

    if name == "agent_job_status":
        return handle_agent_job_status(req_id, arguments)

    if name == "agent_job_list":
        return handle_agent_job_list(req_id, arguments)

    if name == "agent_job_cleanup":
        return handle_agent_job_cleanup(req_id, arguments)

    if name == "smart_agent":
        return handle_smart_agent(req_id, arguments)

    if name == "notion_search":
        return handle_notion_search(req_id, arguments)

    if name == "notion_get_page":
        return handle_notion_get_page(req_id, arguments)

    if name == "mmx_image_generate":
        return handle_mmx_image_generate(req_id, arguments)
    if name == "mmx_video_generate":
        return handle_mmx_video_generate(req_id, arguments)
    if name == "mmx_speech_synthesize":
        return handle_mmx_speech_synthesize(req_id, arguments)
    if name == "mmx_music_generate":
        return handle_mmx_music_generate(req_id, arguments)
    if name == "mmx_vision_describe":
        return handle_mmx_vision_describe(req_id, arguments)
    if name == "mmx_search_query":
        return handle_mmx_search_query(req_id, arguments)
    if name == "mmx_text_chat":
        return handle_mmx_text_chat(req_id, arguments)
    if name == "mmx_quota_show":
        return handle_mmx_quota_show(req_id, arguments)

    if name == "ollama_agent":
        return handle_ollama_agent(req_id, arguments)
    if name == "ollama_list_models":
        return handle_ollama_list_models(req_id, arguments)
    if name == "ollama_generate":
        return handle_ollama_generate(req_id, arguments)
    if name == "ollama_chat":
        return handle_ollama_chat(req_id, arguments)

    # ── 檔案系統
    if name == "fs_list":
        return handle_fs_list(req_id, arguments)
    if name == "fs_read":
        return handle_fs_read(req_id, arguments)
    if name == "fs_write":
        return handle_fs_write(req_id, arguments)
    if name == "fs_move":
        return handle_fs_move(req_id, arguments)
    if name == "fs_delete":
        return handle_fs_delete(req_id, arguments)
    if name == "fs_search":
        return handle_fs_search(req_id, arguments)
    if name == "fs_disk_info":
        return handle_fs_disk_info(req_id, arguments)

    # ── 系統
    if name == "sys_run":
        return handle_sys_run(req_id, arguments)
    if name == "sys_info":
        return handle_sys_info(req_id, arguments)
    if name == "sys_processes":
        return handle_sys_processes(req_id, arguments)

    # ── Git
    if name == "git_status":
        return handle_git_status(req_id, arguments)
    if name == "git_log":
        return handle_git_log(req_id, arguments)
    if name == "git_diff":
        return handle_git_diff(req_id, arguments)
    if name == "git_commit":
        return handle_git_commit(req_id, arguments)

    # ── Playwright
    if name == "browser_screenshot":
        return handle_browser_screenshot(req_id, arguments)
    if name == "browser_get_text":
        return handle_browser_get_text(req_id, arguments)
    if name == "browser_run_script":
        return handle_browser_run_script(req_id, arguments)

    # ── Obsidian
    if name == "vault_read":              return handle_vault_read(req_id, arguments)
    if name == "vault_write":             return handle_vault_write(req_id, arguments)
    if name == "vault_append":            return handle_vault_append(req_id, arguments)
    if name == "vault_list":              return handle_vault_list(req_id, arguments)
    if name == "vault_search":            return handle_vault_search(req_id, arguments)
    if name == "vault_delete":            return handle_vault_delete(req_id, arguments)
    if name == "vault_move":              return handle_vault_move(req_id, arguments)
    if name == "vault_daily_note":        return handle_vault_daily_note(req_id, arguments)
    if name == "vault_recent":            return handle_vault_recent(req_id, arguments)
    if name == "vault_tasks":             return handle_vault_tasks(req_id, arguments)
    if name == "vault_tags":              return handle_vault_tags(req_id, arguments)
    if name == "vault_create_from_template": return handle_vault_create_from_template(req_id, arguments)
    if name == "vault_sort_inbox":           return handle_vault_sort_inbox(req_id, arguments)

    # ── TrackTW
    if name == "tracktw_carriers":
        return handle_tracktw_carriers(req_id, arguments)
    if name == "tracktw_package_status":
        return handle_tracktw_package_status(req_id, arguments)

    # ── 免費圖片生成
    if name == "image_generate_free":
        return handle_image_generate_free(req_id, arguments)

    # ── Web Search
    if name == "web_search":
        return handle_web_search(req_id, arguments)

    # ── Linear
    if name == "linear_issues":
        return handle_linear_issues(req_id, arguments)
    if name == "linear_create_issue":
        return handle_linear_create_issue(req_id, arguments)
    if name == "linear_update_issue":
        return handle_linear_update_issue(req_id, arguments)

    # ── Warp
    if name == "warp_agent_runs_list":
        return handle_warp_agent_runs_list(req_id, arguments)
    if name == "warp_agent_run_status":
        return handle_warp_agent_run_status(req_id, arguments)
    if name == "warp_agent_run_create":
        return handle_warp_agent_run_create(req_id, arguments)

    # ── Cursor
    if name == "cursor_agents_list":
        return handle_cursor_agents_list(req_id, arguments)
    if name == "cursor_agent_get":
        return handle_cursor_agent_get(req_id, arguments)
    if name == "cursor_agent_create":
        return handle_cursor_agent_create(req_id, arguments)
    if name == "cursor_agent_run_status":
        return handle_cursor_agent_run_status(req_id, arguments)

    # ── Factory
    if name == "factory_sessions_list":
        return handle_factory_sessions_list(req_id, arguments)
    if name == "factory_session_get":
        return handle_factory_session_get(req_id, arguments)
    if name == "factory_computers_list":
        return handle_factory_computers_list(req_id, arguments)
    if name == "factory_readiness_reports":
        return handle_factory_readiness_reports(req_id, arguments)

    return make_response(req_id, make_tool_text_response(f"Unknown tool: {name}", is_error=True))


def handle_codex_agent(req_id, arguments: dict) -> dict:
    sync_args, async_response = maybe_start_async_job(req_id, arguments, "codex_agent", run_codex_task)
    if async_response is not None:
        return async_response

    task, working_dir = sync_args
    output, is_error = run_codex_task(task, working_dir)
    return make_response(req_id, make_tool_text_response(output, is_error=is_error))


def handle_gemini_agent(req_id, arguments: dict) -> dict:
    sync_args, async_response = maybe_start_async_job(req_id, arguments, "gemini_agent", run_gemini_task)
    if async_response is not None:
        return async_response

    task, working_dir = sync_args
    output, is_error = run_gemini_task(task, working_dir)
    return make_response(req_id, make_tool_text_response(output, is_error=is_error))


def handle_claude_code_agent(req_id, arguments: dict) -> dict:
    sync_args, async_response = maybe_start_async_job(req_id, arguments, "claude_code_agent", run_claude_code_task)
    if async_response is not None:
        return async_response

    task, working_dir = sync_args
    output, is_error = run_claude_code_task(task, working_dir)
    return make_response(req_id, make_tool_text_response(output, is_error=is_error))


def handle_agent_job_status(req_id, arguments: dict) -> dict:
    job_id = arguments.get("job_id", "").strip()
    if not job_id:
        return make_response(req_id, make_tool_text_response("Error: job_id is required", is_error=True))

    cleanup_expired_jobs()
    job = get_job(job_id)
    if job is None:
        return make_response(req_id, make_tool_text_response(f"Unknown or expired job_id: {job_id}", is_error=True))

    text = build_job_status_text(job)
    is_error = bool(job.get("is_error")) and job.get("status") == "failed"
    return make_response(req_id, make_tool_text_response(text, is_error=is_error))


def handle_agent_job_list(req_id, arguments: dict) -> dict:
    status = (arguments.get("status") or "").strip()
    limit_raw = arguments.get("limit", 20)

    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return make_response(req_id, make_tool_text_response("Error: limit must be an integer", is_error=True))

    if status and status not in {"queued", "running", "succeeded", "failed"}:
        return make_response(
            req_id,
            make_tool_text_response("Error: status must be one of queued/running/succeeded/failed", is_error=True),
        )

    cleanup_expired_jobs()
    jobs = list_jobs(status=status or None, limit=limit)

    if not jobs:
        filter_text = f" (status={status})" if status else ""
        return make_response(req_id, make_tool_text_response(f"No jobs found{filter_text}."))

    lines = [f"Found {len(jobs)} job(s):"]
    for job in jobs:
        lines.append(
            " | ".join(
                [
                    f"job_id={job.get('job_id', '')}",
                    f"tool={job.get('tool', '')}",
                    f"status={job.get('status', '')}",
                    f"updated_at={job.get('updated_at', 0):.0f}",
                ]
            )
        )

    return make_response(req_id, make_tool_text_response("\n".join(lines)))


def handle_agent_job_cleanup(req_id, arguments: dict) -> dict:  # pylint: disable=unused-argument
    removed = cleanup_expired_jobs()
    return make_response(req_id, make_tool_text_response(f"Expired jobs removed: {removed}"))


def handle_smart_agent(req_id, arguments: dict) -> dict:
    sync_args, async_response = maybe_start_async_job(req_id, arguments, "smart_agent", run_smart_agent)
    if async_response is not None:
        return async_response

    task, working_dir = sync_args
    output, is_error, attempts = run_smart_agent(task, working_dir)
    text = output
    if attempts:
        attempt_lines = ["attempts:"]
        for attempt in attempts:
            line = f"- {attempt.get('tool', 'unknown')}: {attempt.get('status', 'unknown')}"
            reason = (attempt.get("reason") or "").strip()
            if reason:
                line += f" ({reason})"
            attempt_lines.append(line)
        text = "\n".join(attempt_lines + ["", output])
    return make_response(req_id, make_tool_text_response(text, is_error=is_error))


# ── Notion helpers ────────────────────────────────────────────────────────────

def _notion_request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    """發送 Notion API 請求，回傳 parsed JSON 或拋出 Exception。"""
    if not NOTION_API_KEY:
        raise ValueError("NOTION_API_KEY not set — add it in Doppler and restart server")
    url = "https://api.notion.com/v1" + path
    data = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_API_KEY}")
    req.add_header("Notion-Version", "2022-06-28")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_plain_text(rich_text_list: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_text_list)


def _page_title(page: dict) -> str:
    props = page.get("properties", {})
    for prop in props.values():
        if prop.get("type") == "title":
            return _extract_plain_text(prop.get("title", []))
    return "(no title)"


def _blocks_to_text(blocks: list) -> str:
    lines = []
    for block in blocks:
        btype = block.get("type", "")
        content = block.get(btype, {})
        rich = content.get("rich_text", [])
        text = _extract_plain_text(rich).strip()
        if text:
            if btype.startswith("heading"):
                lines.append(f"\n## {text}")
            elif btype == "bulleted_list_item":
                lines.append(f"- {text}")
            elif btype == "numbered_list_item":
                lines.append(f"1. {text}")
            elif btype == "to_do":
                checked = "x" if content.get("checked") else " "
                lines.append(f"[{checked}] {text}")
            elif btype == "code":
                lang = content.get("language", "")
                lines.append(f"```{lang}\n{text}\n```")
            else:
                lines.append(text)
    return "\n".join(lines)


def handle_notion_search(req_id, arguments: dict) -> dict:
    query = arguments.get("query", "").strip()
    limit = min(int(arguments.get("limit", 10)), 20)
    if not query:
        return make_response(req_id, make_tool_text_response("Error: query is required", is_error=True))
    try:
        data = _notion_request("/search", "POST", {"query": query, "page_size": limit})
        results = data.get("results", [])
        if not results:
            return make_response(req_id, make_tool_text_response(f"No results found for: {query}"))
        lines = [f"Found {len(results)} result(s) for \"{query}\":\n"]
        for item in results:
            obj_type = item.get("object", "")
            title = _page_title(item) if obj_type == "page" else item.get("title", "(no title)")
            url = item.get("url", "")
            page_id = item.get("id", "")
            lines.append(f"- [{title}]({url})\n  id: {page_id}  type: {obj_type}")
        return make_response(req_id, make_tool_text_response("\n".join(lines)))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Notion search error: {exc}", is_error=True))


def handle_notion_get_page(req_id, arguments: dict) -> dict:
    page_id = arguments.get("page_id", "").strip()
    if not page_id:
        return make_response(req_id, make_tool_text_response("Error: page_id is required", is_error=True))
    # 從 URL 取出 ID（最後一段 32 碼 hex，去掉 dash）
    if page_id.startswith("http"):
        raw = page_id.rstrip("/").split("/")[-1].split("?")[0]
        page_id = raw[-32:].replace("-", "")
        page_id = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
    try:
        page = _notion_request(f"/pages/{page_id}")
        title = _page_title(page)
        url = page.get("url", "")
        blocks_data = _notion_request(f"/blocks/{page_id}/children?page_size=100")
        blocks = blocks_data.get("results", [])
        body = _blocks_to_text(blocks) or "(no content)"
        text = f"# {title}\n{url}\n\n{body}"
        return make_response(req_id, make_tool_text_response(text))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Notion get page error: {exc}", is_error=True))


REQUEST_HANDLERS = {
    "initialize":  handle_initialize,
    "ping":        handle_ping,
    "tools/list":  handle_tools_list,
    "tools/call":  handle_tools_call,
}


def dispatch(msg: dict):
    """處理單一 JSON-RPC 訊息。Notification 回傳 None；Request 回傳 response dict。"""
    method = msg.get("method", "")
    req_id = msg.get("id")          # Notification 沒有 id
    params = msg.get("params") or {}

    if req_id is None:
        log(f"NOTIFICATION {method} (no response)")
        return None

    handler = REQUEST_HANDLERS.get(method)
    if handler is None:
        log(f"METHOD NOT FOUND: {method}")
        return make_error(req_id, -32601, f"Method not found: {method}")

    try:
        return handler(req_id, params)
    except Exception as exc:
        log(f"HANDLER ERROR [{method}]: {exc}")
        return make_error(req_id, -32603, f"Internal error: {exc}")


def handle_discord_webhook_payload(payload: dict) -> tuple[int, dict]:
    if not isinstance(payload, dict):
        return 400, {"ok": False, "error": "Discord webhook payload must be a JSON object"}

    if payload.get("type") == 1:
        return 200, {"type": 1}

    event = {
        "event_id": str(payload.get("id") or uuid.uuid4()),
        "received_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "type": payload.get("type"),
        "guild_id": payload.get("guild_id"),
        "channel_id": payload.get("channel_id"),
        "author": (
            (payload.get("author") or {}).get("username")
            or (payload.get("member") or {}).get("user", {}).get("username")
        ),
        "content": payload.get("content"),
        "raw": payload,
    }
    with DISCORD_WEBHOOK_EVENTS_LOCK:
        DISCORD_WEBHOOK_EVENTS.append(event)
        if len(DISCORD_WEBHOOK_EVENTS) > MAX_DISCORD_WEBHOOK_EVENTS:
            del DISCORD_WEBHOOK_EVENTS[:-MAX_DISCORD_WEBHOOK_EVENTS]

    log(
        "Discord webhook received: "
        f"event_id={event['event_id']} type={event['type']} channel_id={event['channel_id']}"
    )
    return 200, {
        "ok": True,
        "source": "discord",
        "event_id": event["event_id"],
        "stored_events": len(DISCORD_WEBHOOK_EVENTS),
    }


# ─── Linear OAuth (Hermes Agent app) ─────────────────────────────────────────

LINEAR_OAUTH_STATE_LOCK = threading.Lock()
LINEAR_OAUTH_PENDING_STATES: dict[str, float] = {}
LINEAR_OAUTH_STATE_TTL_SECONDS = 600


def linear_oauth_configured() -> bool:
    return bool(LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET)


def linear_oauth_token_present() -> bool:
    token = load_linear_oauth_token()
    return bool(token and token.get("access_token"))


def _prune_linear_oauth_states() -> None:
    cutoff = time.time() - LINEAR_OAUTH_STATE_TTL_SECONDS
    with LINEAR_OAUTH_STATE_LOCK:
        expired = [state for state, created_at in LINEAR_OAUTH_PENDING_STATES.items() if created_at < cutoff]
        for state in expired:
            del LINEAR_OAUTH_PENDING_STATES[state]


def issue_linear_oauth_state() -> str:
    _prune_linear_oauth_states()
    state = secrets.token_urlsafe(24)
    with LINEAR_OAUTH_STATE_LOCK:
        LINEAR_OAUTH_PENDING_STATES[state] = time.time()
    return state


def linear_oauth_state_valid(state: str) -> bool:
    if not state:
        return False
    _prune_linear_oauth_states()
    with LINEAR_OAUTH_STATE_LOCK:
        created_at = LINEAR_OAUTH_PENDING_STATES.get(state)
        if created_at is None:
            return False
        del LINEAR_OAUTH_PENDING_STATES[state]
        return created_at >= time.time() - LINEAR_OAUTH_STATE_TTL_SECONDS


def save_linear_oauth_token(token_data: dict) -> None:
    LINEAR_OAUTH_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **token_data,
        "saved_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "redirect_uri": LINEAR_OAUTH_REDIRECT_URI,
        "client_id": LINEAR_CLIENT_ID,
    }
    LINEAR_OAUTH_TOKEN_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_linear_oauth_token() -> dict | None:
    if not LINEAR_OAUTH_TOKEN_FILE.exists():
        return None
    try:
        data = json.loads(LINEAR_OAUTH_TOKEN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def build_linear_authorize_url(
    state: str | None = None,
    *,
    prompt_consent: bool | None = None,
) -> str:
    if not linear_oauth_configured():
        raise RuntimeError("LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET must be set")
    oauth_state = state or issue_linear_oauth_state()
    params = {
        "client_id": LINEAR_CLIENT_ID,
        "redirect_uri": LINEAR_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": LINEAR_OAUTH_SCOPES,
        "actor": "app",
        "state": oauth_state,
    }
    if prompt_consent if prompt_consent is not None else LINEAR_OAUTH_FORCE_CONSENT:
        params["prompt"] = "consent"
    query = urllib.parse.urlencode(params)
    return f"{LINEAR_AUTHORIZE_URL}?{query}"


def _post_linear_token(body: dict[str, str]) -> dict:
    encoded = urllib.parse.urlencode(body).encode("utf-8")
    req = urllib.request.Request(
        LINEAR_TOKEN_URL,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Linear token exchange failed ({exc.code}): {detail}") from exc
    if not isinstance(payload, dict) or not payload.get("access_token"):
        raise RuntimeError("Linear token exchange returned an unexpected payload")
    return payload


def exchange_linear_oauth_client_credentials() -> dict:
    if not linear_oauth_configured():
        raise RuntimeError("LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET must be set")
    return _post_linear_token({
        "grant_type": "client_credentials",
        "scope": LINEAR_OAUTH_SCOPES,
        "client_id": LINEAR_CLIENT_ID,
        "client_secret": LINEAR_CLIENT_SECRET,
    })


def exchange_linear_oauth_code(code: str) -> dict:
    if not linear_oauth_configured():
        raise RuntimeError("LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET must be set")
    return _post_linear_token({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": LINEAR_OAUTH_REDIRECT_URI,
        "client_id": LINEAR_CLIENT_ID,
        "client_secret": LINEAR_CLIENT_SECRET,
    })


def verify_linear_webhook_signature(raw_body: bytes, signature: str) -> bool:
    if not LINEAR_WEBHOOK_SECRET:
        return True
    if not signature:
        return False
    expected = hmac.new(
        LINEAR_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def linear_oauth_reauth_hint() -> str:
    return (
        "若 Linear 顯示「Hermes Agent already installed」且只有 Cancel / Manage、沒有 Authorize："
        " Linear → Settings → Installed applications → Hermes Agent → Manage → Revoke access，"
        f" 再開 {LINEAR_OAUTH_AUTHORIZE_PATH} 重新授權。"
        f" 或在 Linear OAuth App 開啟 Client credentials 後，開 {LINEAR_OAUTH_BOOTSTRAP_PATH} 自動取 token。"
    )


def linear_oauth_status_payload() -> dict:
    token = load_linear_oauth_token() or {}
    payload = {
        "configured": linear_oauth_configured(),
        "token_present": linear_oauth_token_present(),
        "redirect_uri": LINEAR_OAUTH_REDIRECT_URI,
        "authorize_path": LINEAR_OAUTH_AUTHORIZE_PATH,
        "callback_path": LINEAR_OAUTH_CALLBACK_PATH,
        "bootstrap_path": LINEAR_OAUTH_BOOTSTRAP_PATH,
        "scopes": LINEAR_OAUTH_SCOPES,
        "force_consent": LINEAR_OAUTH_FORCE_CONSENT,
        "webhook_secret_configured": bool(LINEAR_WEBHOOK_SECRET),
        "saved_at": token.get("saved_at"),
        "expires_in": token.get("expires_in"),
        "scope": token.get("scope"),
        "grant_type": token.get("grant_type"),
    }
    if linear_oauth_configured() and not linear_oauth_token_present():
        payload["reauth_hint"] = linear_oauth_reauth_hint()
    return payload


def handle_linear_oauth_bootstrap() -> tuple[int, dict]:
    if not linear_oauth_configured():
        return 503, {
            "error": "not_configured",
            "message": "LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET must be set in Doppler",
        }
    if linear_oauth_token_present():
        token = load_linear_oauth_token() or {}
        return 200, {
            "ok": True,
            "already_present": True,
            "saved_at": token.get("saved_at"),
            "grant_type": token.get("grant_type"),
        }
    try:
        token_data = exchange_linear_oauth_client_credentials()
    except RuntimeError as exc:
        return 502, {
            "error": "client_credentials_failed",
            "message": str(exc),
            "reauth_hint": linear_oauth_reauth_hint(),
        }
    token_data["grant_type"] = "client_credentials"
    save_linear_oauth_token(token_data)
    return 200, {
        "ok": True,
        "already_present": False,
        "grant_type": "client_credentials",
        "expires_in": token_data.get("expires_in"),
        "scope": token_data.get("scope"),
    }


def handle_linear_oauth_callback(query_string: str) -> tuple[int, str, str]:
    params = urllib.parse.parse_qs(query_string)
    error = params.get("error", [""])[0]
    if error:
        description = params.get("error_description", [""])[0]
        return 400, "text/html; charset=utf-8", (
            "<h1>Linear 授權失敗</h1>"
            f"<p>{html_escape(error)}: {html_escape(description)}</p>"
        )

    code = params.get("code", [""])[0]
    state = params.get("state", [""])[0]
    if not code:
        return 400, "text/html; charset=utf-8", "<h1>缺少授權碼</h1><p>Linear 沒有回傳 code。</p>"
    if state and not linear_oauth_state_valid(state):
        return 400, "text/html; charset=utf-8", "<h1>state 無效或已過期</h1><p>請重新從授權頁開始。</p>"

    try:
        token_data = exchange_linear_oauth_code(code)
        save_linear_oauth_token(token_data)
    except RuntimeError as exc:
        return 502, "text/html; charset=utf-8", (
            "<h1>無法換取 Linear token</h1>"
            f"<p>{html_escape(str(exc))}</p>"
        )

    return 200, "text/html; charset=utf-8", (
        "<h1>Hermes Agent × Linear 授權成功</h1>"
        "<p>OAuth token 已安全儲存在 MCP server 本機。</p>"
        "<p>你可以關閉這個分頁。</p>"
    )


# ─── HTTP Handler ─────────────────────────────────────────────────────────────

class MCPHTTPHandler(BaseHTTPRequestHandler):

    # ── GET（探索 / SSE 健康檢查）────────────────────────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/.well-known/oauth-authorization-server":
            if not self._builtin_oauth_enabled_for_request():
                self._send_builtin_oauth_disabled()
                return
            self._handle_oauth_metadata()
        elif path == "/.well-known/oauth-protected-resource":
            if not self._builtin_oauth_enabled_for_request():
                self._send_builtin_oauth_disabled()
                return
            self._handle_resource_metadata()
        elif path == "/.well-known/oauth-protected-resource/mcp":
            if not self._builtin_oauth_enabled_for_request():
                self._send_builtin_oauth_disabled()
                return
            self._handle_resource_metadata(resource_path=MCP_PATH)
        elif path == "/.well-known/openid-configuration":
            if not self._builtin_oauth_enabled_for_request():
                self._send_builtin_oauth_disabled()
                return
            self._handle_openid_configuration()
        elif path == "/authorize":
            if not self._builtin_oauth_enabled_for_request():
                self._send_builtin_oauth_disabled()
                return
            self._handle_authorize(parsed.query)
        elif path == HEALTH_PATH:
            if self._requires_cloudflare_access_for_request(path):
                claims = self._authenticate_public_request_via_cloudflare_access()
                if claims is False:
                    return
                if claims is None and not self._authenticate_bearer_request():
                    return
            self._handle_health()
        elif path == LINEAR_OAUTH_AUTHORIZE_PATH:
            self._handle_linear_oauth_authorize()
        elif path == LINEAR_OAUTH_CALLBACK_PATH:
            self._handle_linear_oauth_callback(parsed.query)
        elif path == LINEAR_OAUTH_STATUS_PATH:
            self._send_oauth_json(linear_oauth_status_payload())
        elif path == LINEAR_OAUTH_BOOTSTRAP_PATH:
            self._handle_linear_oauth_bootstrap()
        elif path == "/mcp":
            if not self._ensure_mcp_request_authorized():
                return
            body = json.dumps({
                "server": SERVER_INFO,
                "protocolVersion": PROTOCOL_VERSION,
            }, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._add_cors_headers()
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    # ── CORS preflight ────────────────────────────────────────────────────────
    def do_OPTIONS(self):
        self.send_response(200)
        self._add_cors_headers()
        self.end_headers()

    # ── OAuth 2.0 helpers ────────────────────────────────────────────────────
    def _send_oauth_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _send_mcp_unauthorized(self, *, error: str, description: str) -> None:
        body = b"Unauthorized"
        self.send_response(401)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "WWW-Authenticate",
            make_www_authenticate_header(self.server.config.base_url, error=error, description=description),
        )
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _handle_oauth_metadata(self) -> None:
        self._send_oauth_json(build_oauth_authorization_server_metadata(self.server.config.base_url))

    def _handle_openid_configuration(self) -> None:
        self._send_oauth_json(build_openid_configuration_metadata(self.server.config.base_url))

    def _handle_resource_metadata(self, resource_path: str = MCP_PATH) -> None:
        base_url = self.server.config.base_url.rstrip("/")
        resource = build_mcp_resource_url(base_url) if resource_path == MCP_PATH else f"{base_url}{resource_path}"
        self._send_oauth_json({
            "resource": resource,
            "authorization_servers": [base_url],
            "scopes_supported": [OAUTH_SCOPE],
            "bearer_methods_supported": ["header"],
            "resource_documentation": build_mcp_resource_url(base_url),
            "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
        })

    def _handle_health(self) -> None:
        base_url = self.server.config.base_url.rstrip("/")
        self._send_oauth_json({
            "ok": True,
            "server": SERVER_INFO,
            "protocolVersion": PROTOCOL_VERSION,
            "local": {
                "host": "0.0.0.0",
                "port": PORT,
                "mcp_path": MCP_PATH,
                "health_path": HEALTH_PATH,
            },
            "public": {
                "base_url": base_url,
                "mcp_url": f"{base_url}{MCP_PATH}",
                "webhook_base_url": (self.server.config.webhook_base_url or self.server.config.base_url).rstrip("/"),
            },
            "auth": {
                "mcp_api_token_configured": bool(self.server.config.mcp_api_token),
                "oauth_public_client_id": OAUTH_STATIC_CLIENT_ID,
                "oauth_active_tokens": len(OAUTH_ACCESS_TOKENS),
                "oauth_mode": (
                    "cloudflare_access_managed"
                    if self.server.config.cloudflare_access_enabled
                    else "handcraft_builtin"
                ),
                "cloudflare_access_enabled": self.server.config.cloudflare_access_enabled,
                "cloudflare_access_aud_configured": bool(self.server.config.cloudflare_access_aud),
            },
            "webhooks": [
                PACKAGE_WEBHOOK_PATH,
                LINEAR_WEBHOOK_PATH,
                LINEAR_WEBHOOK_PATH_ALIAS,
                "/webhook/discord",
            ],
            "linear_oauth": linear_oauth_status_payload(),
        })

    def _handle_linear_oauth_authorize(self) -> None:
        if not linear_oauth_configured():
            self._send_oauth_json({
                "error": "not_configured",
                "message": "LINEAR_CLIENT_ID and LINEAR_CLIENT_SECRET must be set in Doppler",
            }, status=503)
            return
        try:
            location = build_linear_authorize_url()
        except RuntimeError as exc:
            self._send_oauth_json({"error": "oauth_error", "message": str(exc)}, status=503)
            return
        log("Linear OAuth /authorize → redirect to Linear")
        self.send_response(302)
        self.send_header("Location", location)
        self._add_cors_headers()
        self.end_headers()

    def _handle_linear_oauth_callback(self, query_string: str) -> None:
        status, content_type, body = handle_linear_oauth_callback(query_string)
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(encoded)

    def _handle_linear_oauth_bootstrap(self) -> None:
        status, payload = handle_linear_oauth_bootstrap()
        if payload.get("ok"):
            log(f"Linear OAuth /bootstrap → token saved (grant_type={payload.get('grant_type')})")
        else:
            log(f"Linear OAuth /bootstrap failed: {payload.get('error')}")
        self._send_oauth_json(payload, status=status)

    def _handle_authorize(self, query_string: str) -> None:
        params = urllib.parse.parse_qs(query_string)
        response_type = params.get("response_type", [""])[0]
        client_id = params.get("client_id", [""])[0]
        redirect_uri = params.get("redirect_uri", [""])[0]
        state = params.get("state", [""])[0]
        scope = params.get("scope", [OAUTH_SCOPE])[0] or OAUTH_SCOPE
        resource = params.get("resource", [""])[0]
        code_challenge = params.get("code_challenge", [""])[0]
        code_challenge_method = params.get("code_challenge_method", [""])[0]

        client = get_oauth_client(client_id)
        if response_type != "code":
            self._send_oauth_json(oauth_error("unsupported_response_type", "response_type must be code"), 400)
            return
        if not client:
            self._send_oauth_json(oauth_error("invalid_client", "unknown client_id"), 400)
            return
        if not redirect_uri or not oauth_redirect_uri_allowed(client, redirect_uri):
            self._send_oauth_json(oauth_error("invalid_request", "redirect_uri is missing or not registered"), 400)
            return
        if code_challenge:
            code_challenge_method = code_challenge_method or "S256"
            if code_challenge_method != "S256":
                self._send_oauth_json(oauth_error("invalid_request", "PKCE S256 code_challenge is required"), 400)
                return
        elif not client.get("client_secret"):
            self._send_oauth_json(oauth_error("invalid_request", "PKCE S256 code_challenge is required for public clients"), 400)
            return
        if scope and OAUTH_SCOPE not in scope.split():
            self._send_oauth_json(oauth_error("invalid_scope", f"scope must include {OAUTH_SCOPE}"), 400)
            return

        code = secrets.token_urlsafe(32)
        with OAUTH_CODES_LOCK:
            OAUTH_CODES[code] = {
                "created_at": time.time(),
                "used": False,
                "client_id": client_id,
                "scope": scope,
                "resource": resource,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
                "redirect_uri": redirect_uri,
            }
        sep = "&" if "?" in redirect_uri else "?"
        location = f"{redirect_uri}{sep}code={urllib.parse.quote(code)}"
        if state:
            location += f"&state={urllib.parse.quote(state)}"
        log(f"OAuth /authorize → redirect to {redirect_uri[:60]}...")
        self.send_response(302)
        self.send_header("Location", location)
        self._add_cors_headers()
        self.end_headers()

    def _log_token_failure(self, error: str, description: str = "", *, client_id: str = "") -> None:
        label = client_id or "?"
        if description:
            log(f"OAuth /token failed: {error} — {description} (client_id={label})")
        else:
            log(f"OAuth /token failed: {error} (client_id={label})")

    def _handle_token(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length > 0 else b""
        params = parse_request_params(raw, self.headers.get("Content-Type", ""))

        grant_type = params.get("grant_type", "")
        if grant_type != "authorization_code":
            self._log_token_failure("unsupported_grant_type")
            self._send_oauth_json({"error": "unsupported_grant_type"}, 400)
            return

        code = params.get("code", "")
        client_id = params.get("client_id", "")
        redirect_uri = params.get("redirect_uri", "")
        code_verifier = params.get("code_verifier", "")
        resource = params.get("resource", "")
        basic_credentials = parse_basic_client_credentials(self.headers.get("Authorization", ""))
        if basic_credentials and not client_id:
            client_id = basic_credentials[0]
        client = get_oauth_client(client_id)
        if not client:
            self._log_token_failure("invalid_client", client_id=client_id)
            self._send_oauth_json({"error": "invalid_client"}, 401)
            return

        with OAUTH_CODES_LOCK:
            pending_entry = OAUTH_CODES.get(code)

        skip_secret = oauth_token_exchange_skips_client_secret(
            client,
            params,
            code_entry=pending_entry,
        )
        if not skip_secret and not oauth_client_secret_matches(client, params, self.headers.get("Authorization", "")):
            self._log_token_failure("invalid_client", "client_secret mismatch", client_id=client_id)
            self._send_oauth_json({"error": "invalid_client", "error_description": "client_secret mismatch"}, 401)
            return
        with OAUTH_CODES_LOCK:
            entry = OAUTH_CODES.get(code)
            if not entry or entry.get("used"):
                self._log_token_failure("invalid_grant", client_id=client_id)
                self._send_oauth_json({"error": "invalid_grant"}, 400)
                return
            if time.time() - entry["created_at"] > OAUTH_AUTH_CODE_TTL_SECONDS:
                self._log_token_failure("invalid_grant", "code expired", client_id=client_id)
                self._send_oauth_json({"error": "invalid_grant", "error_description": "code expired"}, 400)
                return
            if client_id != entry.get("client_id"):
                self._log_token_failure("invalid_grant", "client_id mismatch", client_id=client_id)
                self._send_oauth_json({"error": "invalid_grant", "error_description": "client_id mismatch"}, 400)
                return
            if redirect_uri != entry.get("redirect_uri"):
                self._log_token_failure("invalid_grant", "redirect_uri mismatch", client_id=client_id)
                self._send_oauth_json({"error": "invalid_grant", "error_description": "redirect_uri mismatch"}, 400)
                return
            if entry.get("resource") and resource and resource != entry.get("resource"):
                self._log_token_failure("invalid_grant", "resource mismatch", client_id=client_id)
                self._send_oauth_json({"error": "invalid_grant", "error_description": "resource mismatch"}, 400)
                return
            if entry.get("code_challenge"):
                if not pkce_verifier_matches(
                    code_verifier,
                    entry.get("code_challenge", ""),
                    entry.get("code_challenge_method", ""),
                ):
                    self._log_token_failure("invalid_grant", "PKCE verification failed", client_id=client_id)
                    self._send_oauth_json({"error": "invalid_grant", "error_description": "PKCE verification failed"}, 400)
                    return
            entry["used"] = True
            scope = entry.get("scope", OAUTH_SCOPE)

        access_token, expires_in = issue_oauth_access_token(client_id, scope)
        log(f"OAuth /token → issued access_token (client_id={client_id})")
        self._send_oauth_json({
            "access_token": access_token,
            "token_type": "Bearer",
            "expires_in": expires_in,
            "scope": scope,
        })

    def _handle_register(self) -> None:
        if not OAUTH_DCR_ENABLED:
            self._send_oauth_json(
                oauth_error(
                    "registration_not_supported",
                    "Use Client ID Metadata Document (CIMD): pass an HTTPS metadata URL as client_id.",
                ),
                404,
            )
            return

        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length > 0 else b""
        meta = parse_request_params(raw, self.headers.get("Content-Type", "application/json"))
        redirect_uris = meta.get("redirect_uris", [])
        if isinstance(redirect_uris, str) and redirect_uris.strip():
            redirect_uris = [redirect_uris.strip()]
        if not isinstance(redirect_uris, list) or not redirect_uris:
            self._send_oauth_json(oauth_error("invalid_client_metadata", "redirect_uris must be a non-empty list"), 400)
            return
        if not all(isinstance(uri, str) and is_safe_oauth_redirect_uri(uri) for uri in redirect_uris):
            self._send_oauth_json(oauth_error("invalid_client_metadata", "redirect_uris must be HTTPS or localhost HTTP"), 400)
            return

        token_endpoint_auth_method = str(meta.get("token_endpoint_auth_method") or "client_secret_post").strip()
        if token_endpoint_auth_method not in {"client_secret_post", "client_secret_basic", "none"}:
            self._send_oauth_json(
                oauth_error("invalid_client_metadata", "token_endpoint_auth_method must be none, client_secret_post, or client_secret_basic"),
                400,
            )
            return

        client_id = secrets.token_urlsafe(24)
        client_secret = "" if token_endpoint_auth_method == "none" else secrets.token_urlsafe(32)
        client = {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": str(meta.get("client_name") or "handcraft OAuth client"),
            "redirect_uris": redirect_uris,
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "created_at": time.time(),
            "source": "dcr",
        }
        with OAUTH_CLIENTS_LOCK:
            OAUTH_CLIENTS[client_id] = client

        response = {
            "client_id": client_id,
            "client_id_issued_at": int(client["created_at"]),
            "redirect_uris": redirect_uris,
            "grant_types": meta.get("grant_types") or ["authorization_code"],
            "response_types": meta.get("response_types") or ["code"],
            "token_endpoint_auth_method": token_endpoint_auth_method,
            "scope": str(meta.get("scope") or OAUTH_SCOPE),
        }
        if client_secret:
            response["client_secret"] = client_secret
            response["client_secret_expires_at"] = 0
        self._send_oauth_json(response, 201)

    # ── 主要端點 ──────────────────────────────────────────────────────────────
    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path).path
        if parsed_path == "/token":
            if not self._builtin_oauth_enabled_for_request():
                self._send_builtin_oauth_disabled()
                return
            self._handle_token()
            return
        if parsed_path == "/register":
            if not self._builtin_oauth_enabled_for_request():
                self._send_builtin_oauth_disabled()
                return
            self._handle_register()
            return
        if parsed_path == "/webhook/discord":
            self._handle_discord_webhook()
            return
        if parsed_path == PACKAGE_WEBHOOK_PATH:
            self._handle_package_webhook()
            return
        if parsed_path == LINEAR_WEBHOOK_PATH or parsed_path == LINEAR_WEBHOOK_PATH_ALIAS:
            self._handle_linear_webhook()
            return
        if parsed_path != MCP_PATH:
            self.send_response(404)
            self.end_headers()
            return

        if not self._ensure_mcp_request_authorized():
            return

        # ── Origin 驗證（spec 強制，防 DNS rebinding）─────────────────────────
        origin = self.headers.get("Origin", "")
        if origin and not self._is_allowed_origin(origin):
            log(f"403 Forbidden: Origin={origin!r}")
            self.send_response(403)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Forbidden: Origin not allowed")
            return

        # ── 讀取 body ─────────────────────────────────────────────────────────
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        log(f"RECV ← {raw.decode('utf-8', errors='replace')}")

        # ── JSON parse ────────────────────────────────────────────────────────
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._send_json(make_error(None, -32700, f"Parse error: {exc}"), status=400)
            return

        if not isinstance(msg, dict):
            self._send_json(make_error(None, -32600, "Invalid Request: expected JSON object"), status=400)
            return

        # ── Dispatch ──────────────────────────────────────────────────────────
        response = dispatch(msg)

        if response is None:
            # Notification → 202 Accepted, 不回 body
            self.send_response(202)
            self._add_cors_headers()
            self.end_headers()
            return

        self._send_json(response)

    def _handle_package_webhook(self) -> None:
        if not self._ensure_webhook_token(self.server.config.package_webhook_token, "package"):
            return
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        raw_text = raw.decode("utf-8", errors="replace")
        log(f"PACKAGE WEBHOOK RECV ← {raw_text}")

        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._send_json(
                    {
                        **make_webhook_response("package", accepted=False),
                        "error": f"Invalid JSON: {exc}",
                    },
                    status=400,
                )
                return
        else:
            payload = {}

        if not isinstance(payload, dict):
            self._send_json(
                {
                    **make_webhook_response("package", accepted=False),
                    "error": "Invalid payload: expected JSON object",
                },
                status=400,
            )
            return

        self._send_json({
            **make_webhook_response("package"),
            "received": True,
        })

    def _handle_linear_webhook(self) -> None:
        if not self._ensure_webhook_token(self.server.config.linear_webhook_token, "linear"):
            return
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length)
        raw_text = raw.decode("utf-8", errors="replace")
        signature = self.headers.get("Linear-Signature", "")
        linear_event = self.headers.get("Linear-Event", "")
        log(f"LINEAR WEBHOOK RECV ← event={linear_event!r} body={raw_text}")

        if LINEAR_WEBHOOK_SECRET and not verify_linear_webhook_signature(raw, signature):
            self._send_json(
                {
                    **make_webhook_response("linear", accepted=False),
                    "error": "Invalid Linear-Signature",
                },
                status=401,
            )
            return

        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                self._send_json(
                    {
                        **make_webhook_response("linear", accepted=False),
                        "error": f"Invalid JSON: {exc}",
                    },
                    status=400,
                )
                return
        else:
            payload = {}

        if not isinstance(payload, dict):
            self._send_json(
                {
                    **make_webhook_response("linear", accepted=False),
                    "error": "Invalid payload: expected JSON object",
                },
                status=400,
            )
            return

        self._send_json({
            **make_webhook_response("linear"),
            "received": True,
        })

    # ── 回應輔助 ──────────────────────────────────────────────────────────────
    def _handle_discord_webhook(self) -> None:
        if not self._ensure_webhook_token(self.server.config.discord_webhook_token, "discord"):
            return
        content_length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._send_json({"ok": False, "error": f"Invalid JSON: {exc}"}, status=400)
            return

        status, response = handle_discord_webhook_payload(payload)
        self._send_json(response, status=status)

    def _send_json(self, obj: dict, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        log(f"SEND → {body.decode('utf-8')}")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._add_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _add_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers",
                         "Content-Type, Authorization, Accept, Mcp-Session-Id, Cf-Access-Jwt-Assertion, X-Handcraft-Webhook-Token, X-Webhook-Token")

    def _is_allowed_origin(self, origin: str) -> bool:
        try:
            hostname = urllib.parse.urlparse(origin).hostname or ""
            return hostname in ALLOWED_HOSTNAMES
        except Exception:
            return False

    def _request_hostname(self) -> str:
        host = self.headers.get("Host", "").split(",")[0].strip()
        return host.split(":")[0].strip().lower()

    def _request_targets_base_hostname(self) -> bool:
        hostname = self._request_hostname()
        return bool(hostname) and hostname == self.server.config.public_hostname

    def _builtin_oauth_enabled_for_request(self) -> bool:
        config = self.server.config
        if not config.cloudflare_access_enabled or not config.cloudflare_access_disable_builtin_oauth:
            return True
        return not self._request_targets_base_hostname()

    def _mcp_auth_required(self) -> bool:
        config = self.server.config
        if self._requires_cloudflare_access_for_request(MCP_PATH):
            return True
        if self._builtin_oauth_enabled_for_request():
            return True
        return bool(config.mcp_api_token)

    def _ensure_mcp_request_authorized(self) -> bool:
        access_claims = None
        if self._requires_cloudflare_access_for_request(MCP_PATH):
            access_claims = self._authenticate_public_request_via_cloudflare_access()
            if access_claims is False:
                return False

        if access_claims is None:
            if not self._authenticate_bearer_request():
                return False
        elif isinstance(access_claims, dict):
            access_identity = access_claims.get("email") or access_claims.get("sub") or "cloudflare-access-user"
            log(f"Cloudflare Access authenticated request: {access_identity}")
        return True

    def _requires_cloudflare_access_for_request(self, path: str) -> bool:
        config = self.server.config
        if not config.cloudflare_access_enabled:
            return False
        if not self._request_targets_base_hostname():
            return False
        return path in {MCP_PATH, HEALTH_PATH}

    def _send_builtin_oauth_disabled(self) -> None:
        self._send_oauth_json(
            oauth_error(
                "not_found",
                "Public OAuth is managed by Cloudflare Access for this hostname.",
            ),
            404,
        )

    def _send_cloudflare_access_unauthorized(self, description: str) -> None:
        self._send_json(
            {
                "ok": False,
                "error": "cloudflare_access_required",
                "error_description": description,
            },
            status=401,
        )

    def _authenticate_public_request_via_cloudflare_access(self):
        access_jwt = self.headers.get("Cf-Access-Jwt-Assertion", "").strip()
        if not access_jwt:
            if self.server.config.cloudflare_access_allow_public_token_fallback:
                return None
            self._send_cloudflare_access_unauthorized(
                "This public endpoint is protected by Cloudflare Access. Complete Managed OAuth in your MCP client and retry.",
            )
            return False
        try:
            return verify_cloudflare_access_jwt(access_jwt, self.server.config)
        except CloudflareAccessAuthError as exc:
            self._send_cloudflare_access_unauthorized(str(exc))
            return False

    def _authenticate_bearer_request(self) -> bool:
        if not self._mcp_auth_required():
            return True

        api_token = self.server.config.mcp_api_token
        auth = self.headers.get("Authorization", "")
        if not auth:
            log("401 Unauthorized: missing token")
            self._send_mcp_unauthorized(
                error="invalid_token",
                description="Missing bearer token. Authorize this MCP app to continue.",
            )
            return False
        token = auth.removeprefix("Bearer ").strip()
        if not bearer_token_is_authorized(token, api_token):
            log("401 Unauthorized: invalid token")
            self._send_mcp_unauthorized(
                error="invalid_token",
                description="Bearer token is invalid or expired. Re-authorize this MCP app.",
            )
            return False
        return True

    def _webhook_token_from_request(self) -> str:
        auth = self.headers.get("Authorization", "").strip()
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        for name in (
            "X-Handcraft-Webhook-Token",
            "X-Webhook-Token",
            "X-Linear-Webhook-Token",
            "X-TrackTW-Webhook-Token",
            "X-Discord-Webhook-Token",
        ):
            value = self.headers.get(name, "").strip()
            if value:
                return value
        return ""

    def _ensure_webhook_token(self, expected_token: str, webhook_name: str) -> bool:
        if not expected_token:
            return True
        supplied = self._webhook_token_from_request()
        if supplied and hmac.compare_digest(supplied, expected_token):
            return True
        self._send_json(
            {
                **make_webhook_response(webhook_name, accepted=False),
                "error": "Missing or invalid webhook secret.",
            },
            status=401,
        )
        return False

    # ── 把 http.server 的 access log 導到 stderr ──────────────────────────────
    def log_message(self, fmt, *args):
        log(f"{self.address_string()} - {fmt % args}")


# ─── 主程式 ───────────────────────────────────────────────────────────────────

def validate_mcp_api_token(raw_token: str | None) -> str:
    api_token = (raw_token or "").strip()
    if not api_token:
        raise RuntimeError("MCP_API_TOKEN must be set to a non-empty value before starting the HTTP server")
    return api_token


def validate_base_url(raw_url: str | None) -> str:
    base_url = (raw_url or "").strip()
    return base_url or "https://mcp.edgars.tools"


def validate_optional_base_url(raw_url: str | None, default_url: str) -> str:
    base_url = (raw_url or "").strip()
    return base_url or default_url


def validate_cloudflare_access_team_domain(raw_domain: str | None) -> str:
    candidate = (raw_domain or "").strip()
    if not candidate:
        return ""
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urllib.parse.urlparse(candidate)
    return (parsed.netloc or parsed.path).rstrip("/").lower()


def validate_cloudflare_access_jwks_url(raw_url: str | None, team_domain: str) -> str:
    candidate = (raw_url or "").strip()
    if candidate:
        return candidate
    if not team_domain:
        return ""
    return f"https://{team_domain}/cdn-cgi/access/certs"


def validate_http_startup_config() -> HandcraftServerConfig:
    base_url = validate_base_url(load_base_url())
    cloudflare_access_enabled = load_bool_env("MCP_CLOUDFLARE_ACCESS_ENABLED", False)
    cloudflare_access_team_domain = validate_cloudflare_access_team_domain(
        load_cloudflare_access_team_domain()
    )
    cloudflare_access_aud = load_cloudflare_access_aud().strip()
    cloudflare_access_jwks_url = validate_cloudflare_access_jwks_url(
        load_cloudflare_access_jwks_url(),
        cloudflare_access_team_domain,
    )

    if cloudflare_access_enabled:
        if jwt is None or PyJWKClient is None:
            raise RuntimeError(
                "PyJWT with PyJWKClient support is required when MCP_CLOUDFLARE_ACCESS_ENABLED=true"
            )
        if not cloudflare_access_team_domain:
            raise RuntimeError(
                "MCP_CLOUDFLARE_ACCESS_TEAM_DOMAIN is required when MCP_CLOUDFLARE_ACCESS_ENABLED=true"
            )
        if not cloudflare_access_aud:
            raise RuntimeError(
                "MCP_CLOUDFLARE_ACCESS_AUD is required when MCP_CLOUDFLARE_ACCESS_ENABLED=true"
            )

    return HandcraftServerConfig(
        mcp_api_token=validate_mcp_api_token(load_mcp_api_token()),
        base_url=base_url,
        webhook_base_url=validate_optional_base_url(load_webhook_base_url(), base_url),
        cloudflare_access_enabled=cloudflare_access_enabled,
        cloudflare_access_team_domain=cloudflare_access_team_domain,
        cloudflare_access_aud=cloudflare_access_aud,
        cloudflare_access_jwks_url=cloudflare_access_jwks_url,
        cloudflare_access_disable_builtin_oauth=load_bool_env(
            "MCP_CLOUDFLARE_ACCESS_DISABLE_BUILTIN_OAUTH",
            True,
        ),
        cloudflare_access_allow_public_token_fallback=load_bool_env(
            "MCP_CLOUDFLARE_ACCESS_ALLOW_PUBLIC_TOKEN_FALLBACK",
            False,
        ),
        package_webhook_token=load_package_webhook_token(),
        linear_webhook_token=load_linear_webhook_token(),
        discord_webhook_token=load_discord_webhook_token(),
    )


def main() -> None:
    try:
        config = validate_http_startup_config()
    except RuntimeError as exc:
        log(f"Startup aborted: {exc}")
        raise SystemExit(1) from None

    server = ThreadingHTTPServer(("0.0.0.0", PORT), MCPHTTPHandler, config=config)
    log(f"handcraft-mcp HTTP server starting")
    log(f"Protocol : {PROTOCOL_VERSION}")
    log(f"Health  : GET  http://localhost:{PORT}{HEALTH_PATH}")
    log(f"Endpoint : POST http://localhost:{PORT}{MCP_PATH}")
    log(f"Webhook : POST http://localhost:{PORT}{PACKAGE_WEBHOOK_PATH}")
    log(f"Webhook : POST http://localhost:{PORT}{LINEAR_WEBHOOK_PATH}")
    log(
        "Auth mode: "
        + (
            "Cloudflare Access managed public endpoint"
            if config.cloudflare_access_enabled
            else "Built-in bearer/OAuth"
        )
    )
    log(f"Linear OAuth authorize: GET http://localhost:{PORT}{LINEAR_OAUTH_AUTHORIZE_PATH}")
    log(f"Linear OAuth callback: GET http://localhost:{PORT}{LINEAR_OAUTH_CALLBACK_PATH}")
    log(f"Allowed origins: {ALLOWED_HOSTNAMES}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("Server stopped (KeyboardInterrupt)")
    finally:
        server.server_close()


def run_ollama_task(task: str, model: str, working_dir: str) -> tuple[str, bool]:
    log(f"ollama_agent: task={task!r} model={model!r} workdir={working_dir!r}")
    try:
        result = run_agent_command(
            ["cmd.exe", "/c", OLLAMA_CMD, "run", model, task],
            cwd=working_dir,
        )
        log(f"ollama_agent: exit_code={result.returncode}")
        return finalize_agent_output(result, fallback_label="Ollama")
    except subprocess.TimeoutExpired:
        return f"ollama_agent timed out after {AGENT_TIMEOUT_SECONDS} seconds", True
    except FileNotFoundError:
        return f"Error: ollama command not found at {OLLAMA_CMD}", True
    except Exception as exc:
        return f"Failed to run Ollama: {exc}", True


def handle_ollama_agent(req_id, arguments: dict) -> dict:
    sync_args, async_response = maybe_start_async_job(req_id, arguments, "ollama_agent",
        lambda t, w: run_ollama_task(t, arguments.get("model", "qwen3.5:latest"), w)
    )
    if async_response is not None:
        return async_response
    task, working_dir = sync_args
    output, is_error = run_ollama_task(task, arguments.get("model", "qwen3.5:latest"), working_dir)
    return make_response(req_id, make_tool_text_response(output, is_error=is_error))


def call_ollama_api(path: str, payload: dict | None = None, *, timeout: float = 120.0) -> dict:
    url = f"{OLLAMA_HOST}{path}"
    data = None
    method = "GET"
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        method = "POST"
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def handle_ollama_list_models(req_id, arguments: dict) -> dict:  # pylint: disable=unused-argument
    try:
        result = call_ollama_api("/api/tags", timeout=30.0)
        return make_response(req_id, make_tool_json_response(result))
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_ollama_generate(req_id, arguments: dict) -> dict:
    model = str(arguments.get("model", "")).strip()
    prompt = str(arguments.get("prompt", "")).strip()
    system_prompt = str(arguments.get("system", "")).strip()
    if not model or not prompt:
        return make_response(req_id, make_tool_text_response("Error: model and prompt are required", is_error=True))

    payload = {"model": model, "prompt": prompt, "stream": False}
    if system_prompt:
        payload["system"] = system_prompt

    try:
        result = call_ollama_api("/api/generate", payload, timeout=float(os.getenv("OLLAMA_MCP_TIMEOUT_SECONDS", "300")))
        text = result.get("response", "")
        response = make_tool_json_response(result)
        response["content"] = [{"type": "text", "text": text}]
        return make_response(req_id, response)
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


def handle_ollama_chat(req_id, arguments: dict) -> dict:
    model = str(arguments.get("model", "")).strip()
    messages = arguments.get("messages")
    if not model or not isinstance(messages, list):
        return make_response(req_id, make_tool_text_response("Error: model and messages are required", is_error=True))

    payload = {"model": model, "messages": messages, "stream": False}
    try:
        result = call_ollama_api("/api/chat", payload, timeout=float(os.getenv("OLLAMA_MCP_TIMEOUT_SECONDS", "300")))
        message = result.get("message", {})
        text = message.get("content", "") if isinstance(message, dict) else ""
        response = make_tool_json_response(result)
        response["content"] = [{"type": "text", "text": text}]
        return make_response(req_id, response)
    except Exception as exc:
        return make_response(req_id, make_tool_text_response(f"Error: {exc}", is_error=True))


# ─── File System Handlers ────────────────────────────────────────────────────

MCP_TRASH_DIR = Path(r"C:\Users\EdgarsTool\.mcp-trash")


def handle_fs_list(req_id, arguments: dict) -> dict:
    path = arguments.get("path", "").strip()
    show_hidden = arguments.get("show_hidden", False)
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = Path(path)
        if not p.exists():
            return make_response(req_id, make_tool_text_response(f"Error: path does not exist: {path}", is_error=True))
        if not p.is_dir():
            return make_response(req_id, make_tool_text_response(f"Error: not a directory: {path}", is_error=True))
        entries = []
        for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if not show_hidden and item.name.startswith("."):
                continue
            try:
                stat = item.stat()
                mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
                kind = "DIR " if item.is_dir() else "FILE"
                size_str = f"{stat.st_size:>12,}" if item.is_file() else "           —"
                entries.append(f"{kind}  {mtime}  {size_str}  {item.name}")
            except (PermissionError, OSError):
                entries.append(f"???   (permission denied)              {item.name}")
        header = f"Directory: {path}\n{len(entries)} item(s)\n" + "─" * 65
        body = "\n".join(entries) if entries else "(empty)"
        return make_response(req_id, make_tool_text_response(f"{header}\n{body}"))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_fs_read(req_id, arguments: dict) -> dict:
    path = arguments.get("path", "").strip()
    max_lines = int(arguments.get("max_lines", 200))
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = Path(path)
        if not p.exists():
            return make_response(req_id, make_tool_text_response(f"Error: file not found: {path}", is_error=True))
        if not p.is_file():
            return make_response(req_id, make_tool_text_response(f"Error: not a file: {path}", is_error=True))
        size = p.stat().st_size
        if size > 5 * 1024 * 1024:
            return make_response(req_id, make_tool_text_response(
                f"Error: file too large ({size:,} bytes). Max 5MB.", is_error=True
            ))
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        total = len(lines)
        if total > max_lines:
            body = "\n".join(lines[:max_lines]) + f"\n... (showing {max_lines}/{total} lines)"
        else:
            body = content
        return make_response(req_id, make_tool_text_response(
            f"File: {path} ({size:,} bytes, {total} lines)\n---\n{body}"
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_fs_write(req_id, arguments: dict) -> dict:
    path = arguments.get("path", "").strip()
    content = arguments.get("content", "")
    append = arguments.get("append", False)
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        with open(p, mode, encoding="utf-8") as f:
            f.write(content)
        action = "Appended to" if append else "Written"
        size = p.stat().st_size
        return make_response(req_id, make_tool_text_response(f"{action}: {path} ({size:,} bytes)"))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_fs_move(req_id, arguments: dict) -> dict:
    src = arguments.get("src", "").strip()
    dst = arguments.get("dst", "").strip()
    if not src or not dst:
        return make_response(req_id, make_tool_text_response("Error: src and dst are required", is_error=True))
    try:
        src_p = Path(src)
        dst_p = Path(dst)
        if not src_p.exists():
            return make_response(req_id, make_tool_text_response(f"Error: source not found: {src}", is_error=True))
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_p), str(dst_p))
        return make_response(req_id, make_tool_text_response(f"Moved: {src} → {dst}"))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_fs_delete(req_id, arguments: dict) -> dict:
    path = arguments.get("path", "").strip()
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = Path(path)
        if not p.exists():
            return make_response(req_id, make_tool_text_response(f"Error: not found: {path}", is_error=True))
        MCP_TRASH_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        trash_dest = MCP_TRASH_DIR / f"{ts}_{p.name}"
        shutil.move(str(p), str(trash_dest))
        return make_response(req_id, make_tool_text_response(
            f"Moved to trash: {path}\nTrash location: {trash_dest}\nTo restore: move it back manually."
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_fs_search(req_id, arguments: dict) -> dict:
    directory = arguments.get("directory", "").strip()
    pattern = arguments.get("pattern", "*").strip()
    search_content = arguments.get("search_content", "")
    max_results = int(arguments.get("max_results", 50))
    if not directory:
        return make_response(req_id, make_tool_text_response("Error: directory is required", is_error=True))
    try:
        d = Path(directory)
        if not d.exists():
            return make_response(req_id, make_tool_text_response(f"Error: directory not found: {directory}", is_error=True))
        matches = []
        for root, dirs, files in os.walk(str(d)):
            dirs[:] = [dd for dd in dirs if not dd.startswith(".")]
            for fname in files:
                if fnmatch.fnmatch(fname.lower(), pattern.lower()):
                    fpath = Path(root) / fname
                    if search_content:
                        try:
                            text = fpath.read_text(encoding="utf-8", errors="replace")
                            if search_content.lower() in text.lower():
                                matches.append(str(fpath))
                        except (PermissionError, OSError):
                            pass
                    else:
                        matches.append(str(fpath))
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break
        if not matches:
            note = f" containing '{search_content}'" if search_content else ""
            return make_response(req_id, make_tool_text_response(
                f"No files matching '{pattern}'{note} found in {directory}"
            ))
        result = f"Found {len(matches)} file(s) (limit {max_results}):\n" + "\n".join(matches)
        return make_response(req_id, make_tool_text_response(result))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_fs_disk_info(req_id, arguments: dict) -> dict:
    try:
        lines = ["Disk Usage", "─" * 55]
        for letter in string.ascii_uppercase:
            drive = f"{letter}:\\"
            if os.path.exists(drive):
                try:
                    usage = shutil.disk_usage(drive)
                    total_gb = usage.total / (1024 ** 3)
                    used_gb = usage.used / (1024 ** 3)
                    free_gb = usage.free / (1024 ** 3)
                    pct = usage.used / usage.total * 100 if usage.total > 0 else 0
                    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                    lines.append(
                        f"{drive}  [{bar}] {pct:4.0f}%  "
                        f"{used_gb:.1f}/{total_gb:.1f} GB  free: {free_gb:.1f} GB"
                    )
                except (PermissionError, OSError):
                    lines.append(f"{drive}  (inaccessible)")
        return make_response(req_id, make_tool_text_response("\n".join(lines)))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


# ─── System Handlers ─────────────────────────────────────────────────────────

_BLOCKED_PATTERNS = [
    "format ", "format.com", "diskpart", "del /f /s /q c:\\",
    "rmdir /s /q c:\\", "rd /s /q c:\\", "rm -rf /", "dd if=",
    "reg delete hklm", "bcdedit", "shutdown /r /o",
]


def handle_sys_run(req_id, arguments: dict) -> dict:
    command = arguments.get("command", "").strip()
    working_dir = arguments.get("working_dir", str(Path.home())).strip()
    timeout = min(int(arguments.get("timeout", 30)), 120)
    if not command:
        return make_response(req_id, make_tool_text_response("Error: command is required", is_error=True))
    cmd_lower = command.lower()
    for blocked in _BLOCKED_PATTERNS:
        if blocked in cmd_lower:
            return make_response(req_id, make_tool_text_response(
                f"Error: blocked command pattern: '{blocked}'", is_error=True
            ))
    try:
        cwd = working_dir if os.path.exists(working_dir) else str(Path.home())
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=timeout, cwd=cwd, shell=False,
        )
        parts = [f"Exit code: {result.returncode}"]
        if result.stdout.strip():
            parts.append(f"STDOUT:\n{result.stdout.strip()}")
        if result.stderr.strip():
            parts.append(f"STDERR:\n{result.stderr.strip()}")
        return make_response(req_id, make_tool_text_response(
            "\n\n".join(parts), is_error=(result.returncode != 0)
        ))
    except subprocess.TimeoutExpired:
        return make_response(req_id, make_tool_text_response(
            f"Error: timed out after {timeout}s", is_error=True
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_sys_info(req_id, arguments: dict) -> dict:
    try:
        lines = [f"OS: {platform.platform()}", f"Python: {sys.version.split()[0]}"]
        cpu_r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Get-CimInstance Win32_Processor | Select-Object -First 1 | "
             "ForEach-Object { \"CPU: $($_.Name) | Cores: $($_.NumberOfCores) | Logical: $($_.NumberOfLogicalProcessors)\" }"],
            capture_output=True, text=True, timeout=10, shell=False,
        )
        if cpu_r.stdout.strip():
            lines.append(cpu_r.stdout.strip())
        ram_r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "$os = Get-CimInstance Win32_OperatingSystem; "
             "$total = [math]::Round($os.TotalVisibleMemorySize/1MB,1); "
             "$free = [math]::Round($os.FreePhysicalMemory/1MB,1); "
             "$used = [math]::Round($total - $free,1); "
             "\"RAM: ${used}GB used / ${total}GB total (${free}GB free)\""],
            capture_output=True, text=True, timeout=10, shell=False,
        )
        if ram_r.stdout.strip():
            lines.append(ram_r.stdout.strip())
        return make_response(req_id, make_tool_text_response("\n".join(lines)))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_sys_processes(req_id, arguments: dict) -> dict:
    limit = int(arguments.get("limit", 20))
    sort_by = arguments.get("sort_by", "memory")
    sort_prop = {"memory": "WorkingSet", "cpu": "CPU", "name": "Name"}.get(sort_by, "WorkingSet")
    sort_dir = "Ascending" if sort_by == "name" else "Descending"
    try:
        ps_cmd = (
            f"Get-Process | Sort-Object {sort_prop} -{sort_dir} | Select-Object -First {limit} | "
            "Format-Table Name, Id, @{N='Mem(MB)';E={[math]::Round($_.WorkingSet/1MB,1)}}, CPU -AutoSize | "
            "Out-String -Width 100"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=20, shell=False,
        )
        return make_response(req_id, make_tool_text_response(
            f"Top {limit} processes (sorted by {sort_by}):\n{result.stdout.strip()}"
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


# ─── Git Handlers ─────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: str, timeout: int = 15) -> tuple[str, bool]:
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=timeout, cwd=cwd, shell=False,
        )
        out = (result.stdout + result.stderr).strip()
        return out, result.returncode != 0
    except subprocess.TimeoutExpired:
        return f"git timed out after {timeout}s", True
    except Exception as e:
        return str(e), True


def handle_git_status(req_id, arguments: dict) -> dict:
    repo = arguments.get("repo_path", "").strip() or CODEX_DEFAULT_WORKDIR
    out, err = _git(["status"], repo)
    return make_response(req_id, make_tool_text_response(out, is_error=err))


def handle_git_log(req_id, arguments: dict) -> dict:
    repo = arguments.get("repo_path", "").strip() or CODEX_DEFAULT_WORKDIR
    limit = int(arguments.get("limit", 10))
    out, err = _git(["log", f"--max-count={limit}", "--oneline", "--decorate"], repo)
    return make_response(req_id, make_tool_text_response(out, is_error=err))


def handle_git_diff(req_id, arguments: dict) -> dict:
    repo = arguments.get("repo_path", "").strip() or CODEX_DEFAULT_WORKDIR
    staged = arguments.get("staged", False)
    args = ["diff", "--stat"] + (["--cached"] if staged else [])
    out, err = _git(args, repo)
    if not out.strip():
        out = "(no diff — working tree is clean)"
    return make_response(req_id, make_tool_text_response(out, is_error=err))


def handle_git_commit(req_id, arguments: dict) -> dict:
    repo = arguments.get("repo_path", "").strip() or CODEX_DEFAULT_WORKDIR
    message = arguments.get("message", "").strip()
    files = arguments.get("files", [])
    if not message:
        return make_response(req_id, make_tool_text_response("Error: message is required", is_error=True))
    add_out, add_err = _git(["add"] + files, repo) if files else _git(["add", "-A"], repo)
    if add_err and "nothing to commit" not in add_out:
        return make_response(req_id, make_tool_text_response(f"Stage failed:\n{add_out}", is_error=True))
    commit_out, commit_err = _git(["commit", "-m", message], repo)
    return make_response(req_id, make_tool_text_response(
        f"Stage:\n{add_out}\n\nCommit:\n{commit_out}", is_error=commit_err
    ))


# ─── Obsidian Vault Handlers ─────────────────────────────────────────────────

def _vault_path(rel: str) -> Path:
    """Resolve relative vault path, block path traversal."""
    p = (VAULT_ROOT / rel).resolve()
    if not str(p).startswith(str(VAULT_ROOT.resolve())):
        raise ValueError(f"Path outside vault: {rel}")
    return p


def _verified_vault_write(path: Path, content: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    verified = path.read_text(encoding="utf-8", errors="replace")
    if verified != content:
        raise SafeMcpWriteError("read-back content did not match written content")
    return path.stat().st_size


def _verified_vault_append(path: Path, content: str) -> int:
    before = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    expected = before + "\n" + content
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + content)
    verified = path.read_text(encoding="utf-8", errors="replace")
    if verified != expected:
        raise SafeMcpWriteError("read-back content did not match appended content")
    return path.stat().st_size


def handle_vault_read(req_id, arguments: dict) -> dict:
    path = arguments.get("path", "").strip()
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = _vault_path(path)
        if not p.exists():
            return make_response(req_id, make_tool_text_response(f"Not found: {path}", is_error=True))
        content = p.read_text(encoding="utf-8", errors="replace")
        return make_response(req_id, make_tool_text_response(f"# {path}\n---\n{content}"))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_vault_write(req_id, arguments: dict) -> dict:
    path    = arguments.get("path", "").strip()
    content = arguments.get("content", "")
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = _vault_path(path)
        size = _verified_vault_write(p, content)
        return make_response(req_id, make_tool_text_response(
            f"Written and verified: {path} ({size:,} bytes)"
        ))
    except SafeMcpWriteError as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_write", path, str(e)), is_error=True
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_write", path, str(e)), is_error=True
        ))


def handle_vault_append(req_id, arguments: dict) -> dict:
    path    = arguments.get("path", "").strip()
    content = arguments.get("content", "")
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = _vault_path(path)
        size = _verified_vault_append(p, content)
        return make_response(req_id, make_tool_text_response(
            f"Appended and verified: {path} ({size:,} bytes)"
        ))
    except SafeMcpWriteError as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_append", path, str(e)), is_error=True
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_append", path, str(e)), is_error=True
        ))


def handle_vault_list(req_id, arguments: dict) -> dict:
    rel = arguments.get("path", "").strip() or "."
    try:
        p = _vault_path(rel)
        if not p.is_dir():
            return make_response(req_id, make_tool_text_response(f"Not a directory: {rel}", is_error=True))
        entries = []
        for item in sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name.lower())):
            if item.name.startswith("."):
                continue
            kind = "📁" if item.is_dir() else "📄"
            entries.append(f"{kind} {item.name}")
        body = "\n".join(entries) if entries else "(empty)"
        return make_response(req_id, make_tool_text_response(f"Vault/{rel}\n{'─'*40}\n{body}"))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_vault_search(req_id, arguments: dict) -> dict:
    query       = arguments.get("query", "").strip()
    max_results = int(arguments.get("max_results", 20))
    if not query:
        return make_response(req_id, make_tool_text_response("Error: query is required", is_error=True))
    try:
        results = []
        query_lower = query.lower()
        for md_file in VAULT_ROOT.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
                if query_lower in text.lower():
                    rel = md_file.relative_to(VAULT_ROOT)
                    # Find snippet
                    idx = text.lower().find(query_lower)
                    start = max(0, idx - 60)
                    snippet = text[start:idx + 100].replace("\n", " ").strip()
                    results.append(f"📄 {rel}\n   …{snippet}…")
                    if len(results) >= max_results:
                        break
            except (PermissionError, OSError):
                pass
        if not results:
            return make_response(req_id, make_tool_text_response(f"No results for: {query}"))
        return make_response(req_id, make_tool_text_response(
            f"Found {len(results)} note(s) matching '{query}':\n\n" + "\n\n".join(results)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_vault_delete(req_id, arguments: dict) -> dict:
    path = arguments.get("path", "").strip()
    if not path:
        return make_response(req_id, make_tool_text_response("Error: path is required", is_error=True))
    try:
        p = _vault_path(path)
        if not p.exists():
            return make_response(req_id, make_tool_text_response(f"Not found: {path}", is_error=True))
        trash = VAULT_ROOT / ".trash"
        trash.mkdir(exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = trash / f"{ts}_{p.name}"
        shutil.move(str(p), str(dest))
        return make_response(req_id, make_tool_text_response(f"Moved to vault .trash: {path}"))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_vault_move(req_id, arguments: dict) -> dict:
    src = arguments.get("src", "").strip()
    dst = arguments.get("dst", "").strip()
    if not src or not dst:
        return make_response(req_id, make_tool_text_response("Error: src and dst are required", is_error=True))
    try:
        src_p = _vault_path(src)
        dst_p = _vault_path(dst)
        if not src_p.exists():
            return make_response(req_id, make_tool_text_response(f"Not found: {src}", is_error=True))
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_p), str(dst_p))
        return make_response(req_id, make_tool_text_response(f"Moved: {src} → {dst}"))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_vault_daily_note(req_id, arguments: dict) -> dict:
    date_str = arguments.get("date", "").strip() or datetime.datetime.now().strftime("%Y-%m-%d")
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
        week = dt.isocalendar()[1]
        day_name = dt.strftime("%A")
        rel_path = f"00 Inbox/Daily/{date_str}.md"
        p = _vault_path(rel_path)

        if p.exists():
            content = p.read_text(encoding="utf-8", errors="replace")
            return make_response(req_id, make_tool_text_response(
                f"Daily note already exists: {rel_path}\n---\n{content}"
            ))

        # Create from template
        content = f"""---
date: {date_str}
week: W{week:02d}
day: {day_name}
tags:
  - daily
---

# {date_str} {day_name}

## 🎯 今日主線
-

## ✅ 手動任務
- [ ]
- [ ]

## 🤖 Agent 對話摘要
-

## 💡 筆記 / 想法
-

## 📊 今日回顧
- **完成了：**
- **卡住了：**
- **明天優先：**
"""
        p.parent.mkdir(parents=True, exist_ok=True)
        _verified_vault_write(p, content)
        return make_response(req_id, make_tool_text_response(
            f"Daily note created: {rel_path}\n---\n{content}"
        ))
    except SafeMcpWriteError as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_daily_note", rel_path, str(e)), is_error=True
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_daily_note", date_str, str(e)), is_error=True
        ))


def handle_vault_recent(req_id, arguments: dict) -> dict:
    limit  = int(arguments.get("limit", 15))
    folder = arguments.get("folder", "").strip()
    try:
        root = _vault_path(folder) if folder else VAULT_ROOT
        files = [
            f for f in root.rglob("*.md")
            if not any(part.startswith(".") for part in f.parts)
        ]
        files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
        lines = []
        for f in files[:limit]:
            rel  = f.relative_to(VAULT_ROOT)
            mtime = datetime.datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"{mtime}  {rel}")
        return make_response(req_id, make_tool_text_response(
            f"Recently modified ({len(lines)} notes):\n\n" + "\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_vault_tasks(req_id, arguments: dict) -> dict:
    folder = arguments.get("folder", "").strip()
    limit  = int(arguments.get("limit", 50))
    try:
        root = _vault_path(folder) if folder else VAULT_ROOT
        tasks = []
        for md_file in root.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue
            try:
                rel = md_file.relative_to(VAULT_ROOT)
                for i, line in enumerate(md_file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if "- [ ]" in line:
                        tasks.append(f"[ ] {line.strip().replace('- [ ]', '').strip()}  ← {rel}:{i}")
                        if len(tasks) >= limit:
                            break
            except (PermissionError, OSError):
                pass
            if len(tasks) >= limit:
                break
        if not tasks:
            return make_response(req_id, make_tool_text_response("No unchecked tasks found! 🎉"))
        return make_response(req_id, make_tool_text_response(
            f"Unchecked tasks ({len(tasks)}):\n\n" + "\n".join(tasks)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_vault_tags(req_id, arguments: dict) -> dict:
    try:
        tag_counts: dict[str, int] = {}
        for md_file in VAULT_ROOT.rglob("*.md"):
            if any(part.startswith(".") for part in md_file.parts):
                continue
            try:
                text = md_file.read_text(encoding="utf-8", errors="replace")
                for tag in re.findall(r"(?<!\w)#([A-Za-z0-9_\-/一-鿿]+)", text):
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1
            except (PermissionError, OSError):
                pass
        if not tag_counts:
            return make_response(req_id, make_tool_text_response("No tags found in vault."))
        sorted_tags = sorted(tag_counts.items(), key=lambda x: -x[1])
        lines = [f"#{tag}  ({count})" for tag, count in sorted_tags]
        return make_response(req_id, make_tool_text_response(
            f"Vault tags ({len(lines)} unique):\n\n" + "\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


# ── Template definitions (Templater syntax stripped, use simple vars) ────────
_VAULT_TEMPLATES: dict[str, str] = {
    "Daily Notes": """---
date: {date}
week: W{week}
day: {day}
tags:
  - daily
---

# {date} {day}

## 🎯 今日主線
- {title}

## ✅ 手動任務
- [ ]
- [ ]

## 🤖 Agent 對話摘要
-

## 💡 筆記 / 想法
-

## 📊 今日回顧
- **完成了：**
- **卡住了：**
- **明天優先：**
""",
    "Project": """---
project: {title}
linear_id: {linear_id}
status: 進行中
priority: {priority}
started: {date}
tags:
  - project
---

# {title}

## 一、目標 Goal
{goal}

## 二、背景 Context

## 三、已凍結方案 Decision
> ⚠️ 尚未凍結

## 四、執行步驟 Plan
- [ ] Step 1：
- [ ] Step 2：
- [ ] Step 3：

## 五、進度 Status
| 日期 | 完成 | 備註 |
|------|------|------|
| {date} | - | 建立 |

## 六、產出 Outputs

## 七、風險 Risks

## 八、下一步 Next

---

## Summary

## Related
-
""",
    "Meeting Notes": """---
date: {date}
attendees: {attendees}
topic: {title}
tags:
  - meeting
---

# 會議記錄：{title}

**日期：** {date}
**出席：** {attendees}

## 📋 議程
-

## 🗣️ 討論重點
-

## ✅ 決議事項
-

## 🔜 後續行動
| 事項 | 負責人 | 截止 |
|------|-------|------|
|  |  |  |

## 💡 備註

## Related
-
""",
    "Weekly Review": """---
week: W{week}
date_start: {date}
tags:
  - weekly-review
---

# 週回顧 W{week}

## ✅ 本週完成了什麼
-

## 🔴 卡住了什麼
-

## 💡 本週學到的
-

## 📊 指標回顧
| 指標 | 目標 | 實際 |
|------|------|------|
| Linear 完成 issue |  |  |
| 新寫筆記 |  |  |

## 🎯 下週優先
1.
2.
3.

## 💬 給下週的自己

""",
    "Decision Record": """---
date: {date}
decision: {title}
status: 提案中
tags:
  - decision
  - adr
---

# 決策記錄：{title}

**日期：** {date}
**狀態：** 提案中 → 進行中 → 已凍結 → 廢棄

## 背景
為什麼需要做這個決定？

## 選項
| 選項 | 優點 | 缺點 |
|------|------|------|
| A |  |  |
| B |  |  |

## 決策
選擇：**{title}**

理由：

## 後果
- 預期：
- 風險：

## Related
-
""",
    "Research Clipping": """---
title: {title}
source: {source}
captured: {date}
tags:
  - clipping
  - research
---

# {title}

> 來源：{source}
> 擷取：{date}

## 核心摘要
1.
2.
3.

## 重點筆記
-

## 我的想法
-

## 行動項目
- [ ]

## Related
-
""",
    "Learning Project": """---
topic: {title}
status: 進行中
started: {date}
tags:
  - learning
---

# {title}

## 🎯 學習目標
-

## 📚 來源資料
- 來源：{source}

## 🗺️ 學習地圖
- [ ] Checkpoint 1：
- [ ] Checkpoint 2：
- [ ] Checkpoint 3：

## 📝 筆記

### 核心概念

### 實作紀錄

### 卡點與解法

## 💡 我的結論 / 心得

## Related
-
""",
    "Service Subscription": """---
service: {title}
plan: {plan}
cost: {cost}
renewal: {renewal}
status: 進行中
tags:
  - service
  - subscription
---

# {title}

## 基本資訊
| 項目 | 內容 |
|------|------|
| 方案 | {plan} |
| 費用 | {cost} |
| 續費日 | {renewal} |
| 帳號 | |

## 目前用途
-

## 評估
- **值得繼續？**
- **可以替代的方案：**

## Related
-
""",
}


def handle_vault_create_from_template(req_id, arguments: dict) -> dict:
    template_name = arguments.get("template", "").strip()
    title         = arguments.get("title", "").strip()
    folder        = arguments.get("folder", "00 Inbox").strip()
    fields        = arguments.get("fields", {}) or {}

    if not template_name or not title:
        return make_response(req_id, make_tool_text_response("Error: template and title are required", is_error=True))

    # Fuzzy match template name
    match = next(
        (k for k in _VAULT_TEMPLATES if template_name.lower() in k.lower()),
        None
    )
    if not match:
        available = ", ".join(_VAULT_TEMPLATES.keys())
        return make_response(req_id, make_tool_text_response(
            f"Template '{template_name}' not found.\nAvailable: {available}", is_error=True
        ))

    now   = datetime.datetime.now()
    week  = now.isocalendar()[1]
    day   = now.strftime("%A")
    today = now.strftime("%Y-%m-%d")

    vars_: dict[str, str] = {
        "title": title, "date": today, "week": f"{week:02d}",
        "day": day, "goal": "", "linear_id": "", "priority": "P2",
        "attendees": "", "source": "", "plan": "", "cost": "", "renewal": "",
    }
    vars_.update({k: str(v) for k, v in fields.items()})

    try:
        content = _VAULT_TEMPLATES[match].format_map(vars_)
    except KeyError as missing:
        content = _VAULT_TEMPLATES[match]  # Fallback: use raw template

    safe_title = re.sub(r'[\\/:*?"<>|]', "-", title)
    rel_path   = f"{folder}/{safe_title}.md"
    p          = _vault_path(rel_path)

    if p.exists():
        return make_response(req_id, make_tool_text_response(
            f"Note already exists: {rel_path}\nUse vault_write to overwrite."
        ))

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        _verified_vault_write(p, content)
        return make_response(req_id, make_tool_text_response(
            f"Created from template '{match}': {rel_path}\n---\n{content}"
        ))
    except SafeMcpWriteError as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_create_from_template", rel_path, str(e)), is_error=True
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Obsidian vault_create_from_template", rel_path, str(e)), is_error=True
        ))


# ─── Vault Sort Inbox ─────────────────────────────────────────────────────────

# 分類規則：關鍵字 → 目標資料夾
_INBOX_RULES: list[tuple[list[str], str]] = [
    # 01 Projects
    (["project", "專案", "企劃", "建置", "規劃", "sprint", "milestone"], "01 Projects"),
    # 02 Areas（持續維護的領域）
    (["agent", "代理", "架構", "架構記錄", "architecture", "環境", "baseline",
      "hermes", "openclaw", "ollama", "ai工具", "報告", "記憶", "mem0",
      "heartbeat", "每日", "daily", "區", "狀態", "status"], "02 Areas"),
    # 03 Resources（參考資料、指令、指南）
    (["指令", "cli", "command", "指南", "guide", "教學", "tutorial", "sync",
      "api", "設定", "config", "連線", "network", "語言", "程式", "code",
      "tool", "工具", "resource", "clipping", "參考", "說明", "手冊"], "03 Resources"),
    # 04 Archive（舊驗證、對話紀錄、已完成）
    (["verify", "驗證", "archive", "封存", "紀錄整理", "對話", "結果",
      "2026-0", "2025-", "old", "舊"], "04 Archive"),
]

def _classify_inbox_note(filename: str, content_snippet: str) -> str:
    """根據檔名和內容前200字判斷目標 PARA 資料夾。"""
    text = (filename + " " + content_snippet).lower()
    for keywords, folder in _INBOX_RULES:
        for kw in keywords:
            if kw.lower() in text:
                return folder
    return "02 Areas"  # 預設：有內容就放 Areas


def handle_vault_sort_inbox(req_id, arguments: dict) -> dict:
    dry_run = bool(arguments.get("dry_run", False))
    inbox   = VAULT_ROOT / "00 Inbox"
    skip_dirs = {"daily notes", "don't touch", "daily"}

    if not inbox.exists():
        return make_response(req_id, make_tool_text_response("Error: 00 Inbox not found", is_error=True))

    moves: list[tuple[Path, Path, str]] = []  # (src, dst, reason)
    skipped: list[str] = []

    for item in sorted(inbox.iterdir()):
        # 跳過子資料夾（只處理根層散落的 .md 檔）
        if item.is_dir():
            if item.name.lower() not in skip_dirs:
                skipped.append(f"[子資料夾跳過] {item.name}/")
            continue
        if item.suffix.lower() != ".md":
            skipped.append(f"[非md跳過] {item.name}")
            continue

        # 讀前200字做分類
        try:
            snippet = item.read_text(encoding="utf-8", errors="ignore")[:200]
        except Exception:
            snippet = ""

        target_folder = _classify_inbox_note(item.stem, snippet)
        dst = VAULT_ROOT / target_folder / item.name
        moves.append((item, dst, target_folder))

    if not moves:
        return make_response(req_id, make_tool_text_response(
            "✅ 00 Inbox 沒有散落的 .md 檔需要整理。" +
            (f"\n\n跳過項目：\n" + "\n".join(skipped) if skipped else "")
        ))

    lines = ["**vault_sort_inbox 結果**", f"模式：{'dry_run（只列出，不搬）' if dry_run else '實際搬移'}", ""]
    errors = []

    for src, dst, folder in moves:
        label = f"  {src.name}  →  {folder}/"
        if dry_run:
            lines.append(f"[預覽] {label}")
        else:
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                lines.append(f"✅ {label}")
            except Exception as e:
                lines.append(f"❌ {label}  ({e})")
                errors.append(str(e))

    if skipped:
        lines += ["", "**跳過（不動）：**"] + [f"  {s}" for s in skipped]

    summary = f"\n共 {len(moves)} 個{'預覽' if dry_run else '已搬移'}，{len(errors)} 個失敗。"
    lines.append(summary)

    return make_response(req_id, make_tool_text_response("\n".join(lines)))


# ─── TrackTW Logistics Handlers ───────────────────────────────────────────────

def _tracktw_key() -> str:
    key = TRACKTW_API_KEY or os.getenv("TRACKTW_API_KEY", "")
    key = key.strip()
    if not key:
        raise ValueError("TRACKTW_API_KEY not set. Add it to Doppler project handcraft-mcp / prd.")
    return key


def _tracktw_request(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict | list:
    url = f"{TRACKTW_BASE_URL}{path}"
    if params:
        query = urllib.parse.urlencode(params)
        url = f"{url}?{query}"

    body = None
    headers = {
        "Authorization": f"Bearer {_tracktw_key()}",
        "Accept": "application/json",
        "User-Agent": "handcraft-mcp/0.1",
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise ValueError(f"TrackTW API error {exc.code}: {error_text}") from exc

    return json.loads(raw) if raw else {}


def _tracktw_get_carriers() -> list[dict]:
    data = _tracktw_request("GET", "/carrier/available")
    if not isinstance(data, list):
        raise ValueError(f"Unexpected carrier response: {data}")
    return data


def _norm_text(value: object) -> str:
    return str(value or "").strip().lower()


def _tracktw_find_carrier(carrier_name: str, carriers: list[dict] | None = None) -> dict:
    query = _norm_text(carrier_name)
    if not query:
        raise ValueError("carrier_name is required")

    carriers = carriers or _tracktw_get_carriers()
    exact = []
    partial = []
    for carrier in carriers:
        name = _norm_text(carrier.get("name"))
        carrier_id = _norm_text(carrier.get("id"))
        if query in {name, carrier_id}:
            exact.append(carrier)
        elif query in name or query in carrier_id:
            partial.append(carrier)

    matches = exact or partial
    if not matches:
        examples = ", ".join(str(c.get("name", "")) for c in carriers[:20])
        raise ValueError(f"找不到物流商/店家：{carrier_name}。可用 tracktw_carriers 查看，例如：{examples}")

    return matches[0]


def _tracktw_import_package(carrier_id: str, tracking_number: str) -> str:
    tracking_number = tracking_number.strip().upper()
    data = _tracktw_request("POST", "/package/import", {
        "carrier_id": carrier_id,
        "tracking_number": [tracking_number],
        "notify_state": "inactive",
    })
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected import response: {data}")

    package_uuid = data.get(tracking_number)
    if not package_uuid:
        package_uuid = data.get(tracking_number.upper())
    if not package_uuid:
        raise ValueError(f"TrackTW 匯入包裹失敗，回傳：{data}")
    return str(package_uuid)


def _tracktw_track_package(package_uuid: str) -> dict:
    data = _tracktw_request("GET", f"/package/tracking/{package_uuid}")
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected tracking response: {data}")
    return data


def _tracking_dt(timestamp: object) -> datetime.datetime | None:
    if isinstance(timestamp, datetime.datetime):
        if timestamp.tzinfo:
            return timestamp.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        return timestamp.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    text = str(timestamp or "").strip()
    if not text:
        return None
    try:
        ts = int(text)
    except (TypeError, ValueError):
        try:
            parsed = datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo:
            return parsed.astimezone(datetime.timezone(datetime.timedelta(hours=8)))
        return parsed.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
    if ts <= 0:
        return None
    return datetime.datetime.fromtimestamp(ts, tz=datetime.timezone(datetime.timedelta(hours=8)))


def _status_text(event: dict) -> str:
    parts = []
    for key in ("status", "location", "description", "message"):
        value = str(event.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)
    return " / ".join(parts) or "狀態未提供"


def _first_text(event: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(event.get(key) or "").strip()
        if value:
            return value
    return ""


def _checkpoint_status_text(event: dict, status_text: str) -> str:
    checkpoint = _first_text(event, (
        "checkpoint_status",
        "checkpointStatus",
        "current_checkpoint_status",
        "checkpoint",
        "substatus",
        "status_code",
    ))
    return checkpoint or _infer_stage(status_text)


def _top_level_history_event(tracking_data: dict) -> dict | None:
    current_status = _first_text(tracking_data, ("current_status", "status", "description", "message"))
    if not current_status:
        return None
    event = {
        "status": current_status,
        "location": str(tracking_data.get("location") or "").strip(),
        "description": _first_text(tracking_data, ("description", "message")),
        "checkpoint_status": _first_text(
            tracking_data,
            ("current_checkpoint_status", "checkpoint_status", "checkpoint"),
        ),
        "time": (
            tracking_data.get("current_event_time")
            or tracking_data.get("event_at")
            or tracking_data.get("time")
            or tracking_data.get("timestamp")
        ),
    }
    return event


def _normalize_history(tracking_data: dict) -> list[dict]:
    raw_history = tracking_data.get("package_history") or tracking_data.get("history") or []
    if not isinstance(raw_history, list):
        raw_history = []
    if not raw_history:
        top_level_event = _top_level_history_event(tracking_data)
        if top_level_event:
            raw_history = [top_level_event]

    events = []
    for item in raw_history:
        if not isinstance(item, dict):
            continue
        dt = _tracking_dt(item.get("time") or item.get("timestamp"))
        status_text = _status_text(item)
        to_status = _first_text(item, ("status", "description", "message")) or status_text
        to_checkpoint_status = _checkpoint_status_text(item, status_text)
        events.append({
            "time": dt.isoformat() if dt else "",
            "time_display": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "current_event_time": dt.isoformat() if dt else "",
            "current_event_time_display": dt.strftime("%Y-%m-%d %H:%M") if dt else "",
            "stage": to_checkpoint_status,
            "current_status": to_status,
            "current_checkpoint_status": to_checkpoint_status,
            "from_status": "",
            "from_checkpoint_status": "",
            "to_status": to_status,
            "to_checkpoint_status": to_checkpoint_status,
            "stage_changed": False,
            "status": str(item.get("status") or "").strip(),
            "location": str(item.get("location") or "").strip(),
            "detail": status_text,
            "raw": item,
            "_sort": dt.timestamp() if dt else 0,
        })

    events.sort(key=lambda event: event["_sort"])
    previous: dict | None = None
    for event in events:
        if previous:
            event["from_status"] = previous["to_status"]
            event["from_checkpoint_status"] = previous["to_checkpoint_status"]
            event["stage_changed"] = (
                event["from_checkpoint_status"] != event["to_checkpoint_status"]
                or event["from_status"] != event["to_status"]
            )
        else:
            event["stage_changed"] = bool(event["to_status"] or event["to_checkpoint_status"])
        event.pop("_sort", None)
        previous = event
    return events


def _infer_stage(text: str) -> str:
    lower = text.lower()
    stage_rules = [
        ("已送達", ["已送達", "配達", "delivered", "取貨完成", "已領取", "簽收"]),
        ("配送中", ["配送中", "派送", "配達中", "out for delivery", "delivering"]),
        ("已到門市/待取", ["到店", "到達門市", "待取", "可取", "arrived at store", "ready for pickup"]),
        ("運送中", ["運送", "轉運", "運輸", "發往", "離開", "transit", "departed", "transport"]),
        ("已到站/集散", ["到達", "抵達", "集散", "營業所", "hub", "facility", "站所"]),
        ("已收件", ["收件", "攬收", "寄件", "已受理", "accepted", "picked up", "received"]),
        ("異常", ["異常", "失敗", "退回", "延誤", "exception", "failed", "return"]),
    ]
    for stage, keywords in stage_rules:
        if any(keyword in lower for keyword in keywords):
            return stage
    return "未知階段"


def _eta_judgement(events: list[dict]) -> dict:
    if not events:
        return {
            "eta": "無法判斷",
            "confidence": "低",
            "reason": "TrackTW 目前沒有貨態紀錄。",
        }

    latest = events[-1]
    stage = latest["stage"]
    latest_time = latest.get("time_display") or "最近一筆"
    if stage == "已送達":
        return {"eta": "已送達", "confidence": "高", "reason": f"最新狀態顯示 {latest_time} 已完成配送/取貨。"}
    if stage in {"配送中", "已到門市/待取"}:
        return {"eta": "今天或明天", "confidence": "中高", "reason": "貨物已進入末端配送或待取階段。"}
    if stage == "已到站/集散":
        return {"eta": "約 1-2 天內", "confidence": "中", "reason": "貨物已到達站所/集散節點，通常接近末端配送。"}
    if stage == "運送中":
        return {"eta": "約 1-3 天內", "confidence": "中", "reason": "貨物仍在跨站運送中，需等下一個站點更新。"}
    if stage == "已收件":
        return {"eta": "約 2-4 天內", "confidence": "中", "reason": "物流已收件，但尚未進入末端配送。"}
    if stage == "異常":
        return {"eta": "需人工確認", "confidence": "低", "reason": "最新狀態含異常/退回/失敗訊號。"}
    return {"eta": "無法判斷", "confidence": "低", "reason": "最新狀態缺少可判斷配送階段的關鍵字。"}


def _tracktw_active_row(
    *,
    label: str,
    carrier_input: str,
    tracking_number: str,
    package_uuid: str,
    current: dict,
) -> dict:
    return {
        "enabled": True,
        "label": label,
        "carrier_keyword": carrier_input,
        "tracking_number": tracking_number,
        "tracktw_uuid": package_uuid,
        "poll_profile": "",
        "current_status": current["to_status"],
        "current_checkpoint_status": current["to_checkpoint_status"],
        "current_event_time": current["current_event_time"],
        "last_checked_at": "",
        "next_check_after": "",
        "last_notified_status": "",
        "last_notified_at": "",
        "picked_up_at": "",
        "archive_after": "",
        "record_state": "active",
        "notify_channel": "",
        "notify_target": "",
        "notes": "",
    }


def _tracktw_event_row(event: dict, *, label: str, carrier_input: str, tracking_number: str) -> dict:
    return {
        "event_at": event["current_event_time"],
        "label": label,
        "carrier_keyword": carrier_input,
        "tracking_number": tracking_number,
        "from_status": event["from_status"],
        "from_checkpoint_status": event["from_checkpoint_status"],
        "to_status": event["to_status"],
        "to_checkpoint_status": event["to_checkpoint_status"],
        "current_event_time": event["current_event_time"],
        "action": "status_changed" if event["stage_changed"] else "status_observed",
        "notify_channel": "",
        "notify_target": "",
        "message": event["detail"],
    }


def _build_tracking_report(carrier_input: str, tracking_number: str, carrier: dict, data: dict) -> dict:
    events = _normalize_history(data)
    current = events[-1] if events else {
        "time": "",
        "time_display": "",
        "current_event_time": "",
        "current_event_time_display": "",
        "stage": "尚無紀錄",
        "current_status": "",
        "current_checkpoint_status": "尚無紀錄",
        "from_status": "",
        "from_checkpoint_status": "",
        "to_status": "",
        "to_checkpoint_status": "尚無紀錄",
        "stage_changed": False,
        "status": "",
        "location": "",
        "detail": "目前無貨態紀錄",
    }
    normalized_tracking_number = str(data.get("tracking_number") or tracking_number).strip().upper()
    package_uuid = str(data.get("id") or data.get("uuid") or "")
    label = carrier.get("name", "") or carrier_input
    active_row = _tracktw_active_row(
        label=label,
        carrier_input=carrier_input,
        tracking_number=normalized_tracking_number,
        package_uuid=package_uuid,
        current=current,
    )
    timeline = [
        _tracktw_event_row(event, label=label, carrier_input=carrier_input, tracking_number=normalized_tracking_number)
        for event in events
    ]
    eta = _eta_judgement(events)
    return {
        "status_model": {
            "source": TRACKTW_STATUS_MODEL_SOURCE,
            "active_fields": list(TRACKTW_ACTIVE_FIELDS),
            "event_fields": list(TRACKTW_EVENT_FIELDS),
        },
        "carrier_input": carrier_input,
        "carrier": {
            "id": carrier.get("id", ""),
            "name": carrier.get("name", ""),
        },
        "tracking_number": normalized_tracking_number,
        "package_uuid": package_uuid,
        "current_stage": current["stage"],
        "current_status": current["to_status"],
        "current_checkpoint_status": current["to_checkpoint_status"],
        "current_event_time": current["current_event_time"],
        "current_event_time_display": current["current_event_time_display"],
        "active_row": active_row,
        "latest_transition": {
            "from_status": current["from_status"],
            "from_checkpoint_status": current["from_checkpoint_status"],
            "to_status": current["to_status"],
            "to_checkpoint_status": current["to_checkpoint_status"],
            "current_event_time": current["current_event_time"],
            "stage_changed": current["stage_changed"],
        },
        "eta": eta,
        "timeline": timeline,
        "history": events,
    }


def _format_tracking_report(report: dict, report_files: list[Path] | None = None) -> str:
    carrier_name = report["carrier"].get("name") or report["carrier_input"]
    lines = [
        "TrackTW 物流查詢結果",
        f"物流商/店家：{carrier_name}",
        f"單號：{report['tracking_number']}",
        f"目前階段：{report['current_stage']}",
        f"目前狀態：{report['current_status']}",
        f"目前 checkpoint：{report['current_checkpoint_status']}",
        f"current_event_time：{report['current_event_time_display'] or report['current_event_time'] or '無'}",
        f"預估到貨：{report['eta']['eta']}（信心：{report['eta']['confidence']}）",
        f"判斷原因：{report['eta']['reason']}",
        "",
        "貨態時間軸（from_status -> to_status）：",
    ]
    if report["history"]:
        for idx, event in enumerate(report["history"], start=1):
            when = event["current_event_time_display"] or event["current_event_time"] or "時間未提供"
            from_status = event["from_status"] or "初始"
            from_checkpoint = event["from_checkpoint_status"] or "初始"
            changed = "stage_changed" if event["stage_changed"] else "stage_same"
            lines.append(
                f"{idx}. {when}｜{from_status} ({from_checkpoint}) -> "
                f"{event['to_status']} ({event['to_checkpoint_status']})｜{changed}｜{event['detail']}"
            )
    else:
        lines.append("- 目前無貨態紀錄")

    if report_files:
        lines += ["", "報告檔案："]
        lines += [f"- {path}" for path in report_files]
    return "\n".join(lines)


def _safe_report_name(carrier_name: str, tracking_number: str, suffix: str) -> str:
    raw = f"tracktw_{carrier_name}_{tracking_number}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.{suffix}"
    return re.sub(r'[\\/:*?"<>|\s]+', "_", raw)


def _write_tracktw_csv(report: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _safe_report_name(report["carrier"].get("name") or report["carrier_input"], report["tracking_number"], "csv")
    rows = [
        ["項目", "內容"],
        ["物流商/店家", report["carrier"].get("name") or report["carrier_input"]],
        ["單號", report["tracking_number"]],
        ["目前階段", report["current_stage"]],
        ["目前狀態", report["current_status"]],
        ["目前 checkpoint", report["current_checkpoint_status"]],
        ["current_event_time", report["current_event_time_display"] or report["current_event_time"]],
        ["預估到貨", report["eta"]["eta"]],
        ["信心", report["eta"]["confidence"]],
        ["判斷原因", report["eta"]["reason"]],
        [],
        ["序號", "current_event_time", "from_status", "from_checkpoint_status", "to_status", "to_checkpoint_status", "stage_changed", "地點", "詳細內容"],
    ]
    for idx, event in enumerate(report["history"], start=1):
        rows.append([
            idx,
            event["current_event_time_display"] or event["current_event_time"],
            event["from_status"],
            event["from_checkpoint_status"],
            event["to_status"],
            event["to_checkpoint_status"],
            event["stage_changed"],
            event["location"],
            event["detail"],
        ])

    def csv_cell(value: object) -> str:
        text = str(value)
        if any(ch in text for ch in [",", '"', "\n", "\r"]):
            text = '"' + text.replace('"', '""') + '"'
        return text

    content = "\ufeff" + "\r\n".join(",".join(csv_cell(cell) for cell in row) for row in rows)
    path.write_text(content, encoding="utf-8")
    return path


def _xlsx_col(col_idx: int) -> str:
    letters = ""
    while col_idx:
        col_idx, rem = divmod(col_idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _xlsx_sheet_xml(rows: list[list[object]]) -> str:
    xml_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            ref = f"{_xlsx_col(col_idx)}{row_idx}"
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                text = html_escape(str(value or ""), quote=False)
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        xml_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'
        f'<sheetData>{"".join(xml_rows)}</sheetData>'
        '</worksheet>'
    )


def _write_tracktw_xlsx(report: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _safe_report_name(report["carrier"].get("name") or report["carrier_input"], report["tracking_number"], "xlsx")
    summary_rows = [
        ["TrackTW 物流報告", ""],
        ["物流商/店家", report["carrier"].get("name") or report["carrier_input"]],
        ["物流商 ID", report["carrier"].get("id")],
        ["單號", report["tracking_number"]],
        ["目前階段", report["current_stage"]],
        ["目前狀態", report["current_status"]],
        ["目前 checkpoint", report["current_checkpoint_status"]],
        ["current_event_time", report["current_event_time_display"] or report["current_event_time"]],
        ["預估到貨", report["eta"]["eta"]],
        ["信心", report["eta"]["confidence"]],
        ["判斷原因", report["eta"]["reason"]],
    ]
    history_rows = [["序號", "current_event_time", "from_status", "from_checkpoint_status", "to_status", "to_checkpoint_status", "stage_changed", "地點", "詳細內容"]]
    for idx, event in enumerate(report["history"], start=1):
        history_rows.append([
            idx,
            event["current_event_time_display"] or event["current_event_time"],
            event["from_status"],
            event["from_checkpoint_status"],
            event["to_status"],
            event["to_checkpoint_status"],
            event["stage_changed"],
            event["location"],
            event["detail"],
        ])

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>""")
        zf.writestr("_rels/.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""")
        zf.writestr("xl/workbook.xml", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
<sheets>
<sheet name="Summary" sheetId="1" r:id="rId1"/>
<sheet name="History" sheetId="2" r:id="rId2"/>
</sheets>
</workbook>""")
        zf.writestr("xl/_rels/workbook.xml.rels", """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>""")
        zf.writestr("xl/worksheets/sheet1.xml", _xlsx_sheet_xml(summary_rows))
        zf.writestr("xl/worksheets/sheet2.xml", _xlsx_sheet_xml(history_rows))
    return path


def _write_tracktw_reports(report: dict, report_format: str, output_dir: str | None) -> list[Path]:
    output_path = Path(output_dir).expanduser() if output_dir else REPORTS_DIR
    fmt = (report_format or "xlsx").strip().lower()
    if fmt not in {"xlsx", "csv", "both"}:
        raise ValueError("report_format must be xlsx, csv, or both")

    paths = []
    if fmt in {"xlsx", "both"}:
        paths.append(_write_tracktw_xlsx(report, output_path))
    if fmt in {"csv", "both"}:
        paths.append(_write_tracktw_csv(report, output_path))
    return paths


def handle_tracktw_carriers(req_id, arguments: dict) -> dict:
    query = _norm_text(arguments.get("query", ""))
    limit = min(max(int(arguments.get("limit", 50)), 1), 200)
    try:
        carriers = _tracktw_get_carriers()
        if query:
            carriers = [
                carrier for carrier in carriers
                if query in _norm_text(carrier.get("name")) or query in _norm_text(carrier.get("id"))
            ]
        carriers = carriers[:limit]
        if not carriers:
            return make_response(req_id, make_tool_text_response("TrackTW 沒有找到符合的物流商。"))
        lines = ["TrackTW 可用物流商："]
        for carrier in carriers:
            lines.append(f"- {carrier.get('name', '')} ({carrier.get('id', '')})")
        return make_response(req_id, make_tool_text_response("\n".join(lines)))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_tracktw_package_status(req_id, arguments: dict) -> dict:
    carrier_name = str(arguments.get("carrier_name") or "").strip()
    tracking_number = str(arguments.get("tracking_number") or "").strip()
    if not carrier_name:
        return make_response(req_id, make_tool_text_response("Error: carrier_name is required", is_error=True))
    if not tracking_number:
        return make_response(req_id, make_tool_text_response("Error: tracking_number is required", is_error=True))

    try:
        carrier = _tracktw_find_carrier(carrier_name)
        package_uuid = _tracktw_import_package(str(carrier["id"]), tracking_number)
        data = _tracktw_track_package(package_uuid)
        report = _build_tracking_report(carrier_name, tracking_number, carrier, data)
        if not report.get("package_uuid"):
            report["package_uuid"] = package_uuid
            report["active_row"]["tracktw_uuid"] = package_uuid

        report_files = []
        if bool(arguments.get("export_report", False)):
            report_files = _write_tracktw_reports(
                report,
                str(arguments.get("report_format") or "xlsx"),
                arguments.get("output_dir"),
            )

        return make_response(req_id, make_tool_text_response(_format_tracking_report(report, report_files)))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


# ─── Free Image Generation (Pollinations.AI) ─────────────────────────────────

def handle_image_generate_free(req_id, arguments: dict) -> dict:
    prompt = arguments.get("prompt", "").strip()
    if not prompt:
        return make_response(req_id, make_tool_text_response("Error: prompt is required", is_error=True))
    width  = int(arguments.get("width",  1024))
    height = int(arguments.get("height", 1024))
    model  = arguments.get("model", "flux").strip() or "flux"
    seed   = arguments.get("seed")

    try:
        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width={width}&height={height}&model={model}&nologo=true"
        if seed is not None:
            url += f"&seed={seed}"

        log(f"image_generate_free: fetching {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "handcraft-mcp/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            img_bytes = resp.read()

        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = SCREENSHOTS_DIR / f"pollinations_{ts}.png"
        fname.write_bytes(img_bytes)

        return make_response(req_id, make_tool_text_response(
            f"Image saved: {fname}\n"
            f"Prompt: {prompt}\n"
            f"Model: {model}  Size: {width}x{height}  ({len(img_bytes):,} bytes)\n"
            f"Source: Pollinations.AI (free, no key)"
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


# ─── Playwright Handlers ─────────────────────────────────────────────────────

def _pw_launch():
    """Import playwright sync API lazily."""
    from playwright.sync_api import sync_playwright  # noqa: PLC0415
    return sync_playwright


def handle_browser_screenshot(req_id, arguments: dict) -> dict:
    url = arguments.get("url", "").strip()
    wait_ms = int(arguments.get("wait_ms", 2000))
    full_page = bool(arguments.get("full_page", False))
    if not url:
        return make_response(req_id, make_tool_text_response("Error: url is required", is_error=True))
    try:
        SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = SCREENSHOTS_DIR / f"screenshot_{ts}.png"
        sync_playwright = _pw_launch()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            page.screenshot(path=str(fname), full_page=full_page)
            title = page.title()
            browser.close()
        return make_response(req_id, make_tool_text_response(
            f"Screenshot saved: {fname}\nPage title: {title}\nURL: {url}"
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_browser_get_text(req_id, arguments: dict) -> dict:
    url = arguments.get("url", "").strip()
    selector = arguments.get("selector", "body").strip() or "body"
    wait_ms = int(arguments.get("wait_ms", 1000))
    if not url:
        return make_response(req_id, make_tool_text_response("Error: url is required", is_error=True))
    try:
        sync_playwright = _pw_launch()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            try:
                text = page.locator(selector).first.inner_text(timeout=5000)
            except Exception:
                text = page.evaluate("document.body.innerText")
            title = page.title()
            browser.close()
        text = text.strip()
        if len(text) > 8000:
            text = text[:8000] + f"\n... (truncated, original length: {len(text)} chars)"
        return make_response(req_id, make_tool_text_response(
            f"URL: {url}\nTitle: {title}\nSelector: {selector}\n---\n{text}"
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_browser_run_script(req_id, arguments: dict) -> dict:
    url = arguments.get("url", "").strip()
    script = arguments.get("script", "").strip()
    wait_ms = int(arguments.get("wait_ms", 1000))
    if not url or not script:
        return make_response(req_id, make_tool_text_response("Error: url and script are required", is_error=True))
    try:
        sync_playwright = _pw_launch()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            if wait_ms:
                page.wait_for_timeout(wait_ms)
            result = page.evaluate(script)
            browser.close()
        result_str = json.dumps(result, ensure_ascii=False, indent=2) if result is not None else "null"
        if len(result_str) > 5000:
            result_str = result_str[:5000] + "\n... (truncated)"
        return make_response(req_id, make_tool_text_response(
            f"URL: {url}\nScript result:\n{result_str}"
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


# ─── Web Search Handler ───────────────────────────────────────────────────────

def handle_web_search(req_id, arguments: dict) -> dict:
    query = arguments.get("query", "").strip()
    if not query:
        return make_response(req_id, make_tool_text_response("Error: query is required", is_error=True))
    if not PERPLEXITY_API_KEY:
        return make_response(req_id, make_tool_text_response(
            "Error: PERPLEXITY_API_KEY not set. Add to Doppler: handcraft-mcp / prd", is_error=True
        ))
    try:
        payload = json.dumps({
            "model": "llama-3.1-sonar-small-128k-online",
            "messages": [{"role": "user", "content": query}],
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.perplexity.ai/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        citations = data.get("citations", [])
        result = content
        if citations:
            result += "\n\nSources:\n" + "\n".join(f"- {c}" for c in citations[:5])
        return make_response(req_id, make_tool_text_response(result))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


# ─── Linear Handlers ──────────────────────────────────────────────────────────

def _linear_graphql(query: str, variables: dict | None = None) -> dict:
    if not LINEAR_API_KEY:
        raise LinearMcpError("LINEAR_API_KEY not set in Doppler")
    payload = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.linear.app/graphql",
        data=payload,
        headers={
            "Authorization": LINEAR_API_KEY,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise LinearMcpError(f"Linear HTTP {e.code}: {body[:500]}") from e
    except urllib.error.URLError as e:
        raise LinearMcpError(f"Linear connection failed: {e.reason}") from e
    except json.JSONDecodeError as e:
        raise LinearMcpError(f"Linear returned invalid JSON: {e}") from e

    errors = data.get("errors")
    if errors:
        reasons = []
        for err in errors:
            if isinstance(err, dict):
                reasons.append(str(err.get("message") or err))
            else:
                reasons.append(str(err))
        raise LinearMcpError("; ".join(reasons))
    return data


def _linear_issue_by_identifier(identifier: str, *, include_comments: bool = False) -> dict | None:
    identifier = (identifier or "").strip()
    if not identifier:
        return None

    comments = "comments(last: 5) { nodes { id body createdAt } }" if include_comments else ""
    issue_fields = f"""
                id identifier title url
                state {{ name }}
                team {{ states {{ nodes {{ id name }} }} }}
                {comments}
    """

    identifier_match = re.match(r"^([A-Za-z][A-Za-z0-9_]*)-(\d+)$", identifier)
    if identifier_match:
        team_key, issue_number = identifier_match.groups()
        query = f"""
        query LinearIssueByKeyAndNumber($teamKey: String!, $issueNumber: Int!) {{
            issues(filter: {{
                team: {{ key: {{ eqIgnoreCase: $teamKey }} }}
                number: {{ eq: $issueNumber }}
            }} first: 1) {{
                nodes {{
{issue_fields}
                }}
            }}
        }}
        """
        data = _linear_graphql(query, {
            "teamKey": team_key,
            "issueNumber": int(issue_number),
        })
        nodes = data["data"]["issues"]["nodes"]
        return nodes[0] if nodes else None

    uuid_match = re.match(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$",
        identifier,
    )
    if uuid_match:
        query = f"""
        query LinearIssueByUuid($id: String!) {{
            issue(id: $id) {{
{issue_fields}
            }}
        }}
        """
        data = _linear_graphql(query, {"id": identifier})
        return data["data"].get("issue")

    return None


def handle_linear_issues(req_id, arguments: dict) -> dict:
    state = arguments.get("state", "").strip()
    limit = int(arguments.get("limit", 10))
    assignee_me = bool(arguments.get("assignee_me", False))
    try:
        filter_parts = []
        if state:
            filter_parts.append(f'state: "{{ name: \"{state}\" }}"')
        if assignee_me:
            filter_parts.append('assignee: { isMe: true }')
        filter_clause = f"filter: {{ {', '.join(filter_parts)} }}" if filter_parts else ""
        gql = f"""
        query {{
            issues({filter_clause} first: {limit} orderBy: updatedAt) {{
                nodes {{
                    identifier title
                    state {{ name }}
                    priority
                    assignee {{ name }}
                    updatedAt
                }}
            }}
        }}
        """
        data = _linear_graphql(gql)
        issues = data["data"]["issues"]["nodes"]
        if not issues:
            return make_response(req_id, make_tool_text_response("No issues found."))
        prio_map = {0: "—", 1: "🔴 Urgent", 2: "🟠 High", 3: "🟡 Medium", 4: "🟢 Low"}
        lines = []
        for iss in issues:
            prio = prio_map.get(iss.get("priority", 0), "—")
            assignee = iss.get("assignee", {}) or {}
            lines.append(
                f"[{iss['identifier']}] {iss['title']}\n"
                f"  State: {iss['state']['name']}  Priority: {prio}  "
                f"Assignee: {assignee.get('name', '—')}"
            )
        return make_response(req_id, make_tool_text_response(
            f"Linear issues ({len(issues)}):\n\n" + "\n\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_linear_create_issue(req_id, arguments: dict) -> dict:
    title = arguments.get("title", "").strip()
    description = arguments.get("description", "").strip()
    team_name = arguments.get("team_name", "").strip()
    priority = int(arguments.get("priority", 3))
    if not title:
        return make_response(req_id, make_tool_text_response("Error: title is required", is_error=True))
    try:
        # Get team ID
        teams_data = _linear_graphql("query { teams { nodes { id name } } }")
        teams = teams_data["data"]["teams"]["nodes"]
        if not teams:
            return make_response(req_id, make_tool_text_response("Error: no teams found", is_error=True))
        team = next((t for t in teams if team_name.lower() in t["name"].lower()), teams[0])
        team_id = team["id"]

        mutation = """
        mutation CreateIssue($teamId: String!, $title: String!, $description: String, $priority: Int) {
            issueCreate(input: { teamId: $teamId, title: $title, description: $description, priority: $priority }) {
                issue { identifier title url }
            }
        }
        """
        result = _linear_graphql(mutation, {
            "teamId": team_id, "title": title,
            "description": description or None, "priority": priority,
        })
        iss = result["data"]["issueCreate"]["issue"]
        verified = _linear_issue_by_identifier(iss["identifier"])
        if not verified:
            return make_response(req_id, make_tool_text_response(
                format_safe_mcp_failure("Linear issue create", title, "created issue could not be re-fetched"),
                is_error=True,
            ))
        if verified["title"] != title:
            return make_response(req_id, make_tool_text_response(
                format_safe_mcp_failure(
                    "Linear issue create",
                    iss["identifier"],
                    f"read-back title mismatch: expected {title!r}, got {verified['title']!r}",
                ),
                is_error=True,
            ))
        return make_response(req_id, make_tool_text_response(
            f"Created and verified: [{verified['identifier']}] {verified['title']}\nURL: {verified['url']}"
        ))
    except LinearMcpError as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Linear issue create", title or "(missing title)", str(e)), is_error=True
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Linear issue create", title or "(missing title)", str(e)), is_error=True
        ))


def handle_linear_update_issue(req_id, arguments: dict) -> dict:
    issue_id = arguments.get("issue_id", "").strip()
    state_name = arguments.get("state", "").strip()
    comment = arguments.get("comment", "").strip()
    if not issue_id:
        return make_response(req_id, make_tool_text_response("Error: issue_id is required", is_error=True))
    try:
        results = []
        # Resolve issue UUID from identifier
        iss = _linear_issue_by_identifier(issue_id)
        if not iss:
            return make_response(req_id, make_tool_text_response(f"Issue not found: {issue_id}", is_error=True))
        iss_uuid = iss["id"]

        if state_name:
            states = iss["team"]["states"]["nodes"]
            state = next((s for s in states if state_name.lower() in s["name"].lower()), None)
            if not state:
                available = ", ".join(s["name"] for s in states)
                return make_response(req_id, make_tool_text_response(
                    f"State '{state_name}' not found. Available: {available}", is_error=True
                ))
            update_m = """
            mutation UpdateIssue($id: String!, $stateId: String!) {
                issueUpdate(id: $id, input: { stateId: $stateId }) {
                    issue { identifier state { name } }
                }
            }
            """
            upd = _linear_graphql(update_m, {"id": iss_uuid, "stateId": state["id"]})
            updated = upd["data"]["issueUpdate"]["issue"]
            results.append(f"State updated → {updated['state']['name']}")

        if comment:
            comment_m = """
            mutation AddComment($issueId: String!, $body: String!) {
                commentCreate(input: { issueId: $issueId, body: $body }) {
                    comment { id body }
                }
            }
            """
            comment_result = _linear_graphql(comment_m, {"issueId": iss_uuid, "body": comment})
            comment_id = comment_result["data"]["commentCreate"]["comment"]["id"]
            results.append("Comment added")

        if not results:
            return make_response(req_id, make_tool_text_response("Nothing to update (provide state or comment)"))

        verified = _linear_issue_by_identifier(issue_id, include_comments=bool(comment))
        if not verified:
            return make_response(req_id, make_tool_text_response(
                format_safe_mcp_failure("Linear issue update", issue_id, "updated issue could not be re-fetched"),
                is_error=True,
            ))
        verification = []
        if state_name:
            verified_state = verified["state"]["name"]
            if verified_state != updated["state"]["name"]:
                return make_response(req_id, make_tool_text_response(
                    format_safe_mcp_failure(
                        "Linear issue update",
                        issue_id,
                        f"state read-back mismatch: expected {updated['state']['name']!r}, got {verified_state!r}",
                    ),
                    is_error=True,
                ))
            verification.append(f"Verified state: {verified_state}")
        if comment:
            comment_nodes = verified.get("comments", {}).get("nodes", [])
            if not any(node.get("id") == comment_id for node in comment_nodes):
                return make_response(req_id, make_tool_text_response(
                    format_safe_mcp_failure(
                        "Linear issue update",
                        issue_id,
                        "created comment was not present in recent comments read-back",
                    ),
                    is_error=True,
                ))
            verification.append(f"Verified comment: {comment_id}")

        return make_response(req_id, make_tool_text_response(
            f"[{issue_id}] {iss['title']}\n" + "\n".join(results + verification)
        ))
    except LinearMcpError as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Linear issue update", issue_id, str(e)), is_error=True
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Linear issue update", issue_id, str(e)), is_error=True
        ))


# ─── Warp Oz Cloud Agents Handlers ────────────────────────────────────────────

def _warp_key() -> str:
    key = (WARP_API_KEY or os.getenv("WARP_API_KEY", "")).strip()
    if not key:
        raise WarpMcpError("WARP_API_KEY not set. Add it to Doppler project handcraft-mcp / prd.")
    return key


def _warp_request(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict | list:
    url = f"{WARP_BASE_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {
        "Authorization": f"Bearer {_warp_key()}",
        "Accept": "application/json",
        "User-Agent": "handcraft-mcp/0.1",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise WarpMcpError(f"Warp API error {exc.code}: {error_text[:800]}") from exc
    except urllib.error.URLError as exc:
        raise WarpMcpError(f"Warp connection failed: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WarpMcpError(f"Warp returned invalid JSON: {exc}") from exc


def _format_warp_run_line(run: dict) -> str:
    run_id = run.get("run_id") or run.get("id") or "—"
    state = run.get("state") or run.get("status") or "—"
    title = run.get("title") or run.get("name") or run.get("prompt", "—")
    if isinstance(title, dict):
        title = title.get("text") or title.get("prompt") or "—"
    created = run.get("created_at") or run.get("createdAt") or ""
    return f"[{run_id}] {state} — {title}" + (f" ({created})" if created else "")


def handle_warp_agent_runs_list(req_id, arguments: dict) -> dict:
    limit = int(arguments.get("limit", 10))
    try:
        data = _warp_request("GET", "/agent/runs", params={"limit": limit})
        runs = data if isinstance(data, list) else data.get("runs") or data.get("items") or []
        if not runs:
            return make_response(req_id, make_tool_text_response("No Warp agent runs found."))
        lines = [_format_warp_run_line(run) for run in runs[:limit]]
        return make_response(req_id, make_tool_text_response(
            f"Warp agent runs ({len(lines)}):\n\n" + "\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_warp_agent_run_status(req_id, arguments: dict) -> dict:
    run_id = (arguments.get("run_id") or "").strip()
    if not run_id:
        return make_response(req_id, make_tool_text_response("Error: run_id is required", is_error=True))
    try:
        data = _warp_request("GET", f"/agent/runs/{urllib.parse.quote(run_id, safe='')}")
        return make_response(req_id, make_tool_json_response(data))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Warp agent run status", run_id, str(e)), is_error=True
        ))


def handle_warp_agent_run_create(req_id, arguments: dict) -> dict:
    prompt = (arguments.get("prompt") or "").strip()
    environment_id = (arguments.get("environment_id") or "").strip()
    title = (arguments.get("title") or "").strip()
    if not prompt:
        return make_response(req_id, make_tool_text_response("Error: prompt is required", is_error=True))
    if not environment_id:
        return make_response(req_id, make_tool_text_response("Error: environment_id is required", is_error=True))
    try:
        payload: dict = {
            "prompt": prompt,
            "config": {"environment_id": environment_id},
        }
        if title:
            payload["title"] = title
        data = _warp_request("POST", "/agent/run", payload=payload)
        run_id = data.get("run_id") or data.get("id") or "—"
        state = data.get("state") or data.get("status") or "created"
        return make_response(req_id, make_tool_text_response(
            f"Warp agent run started.\nrun_id: {run_id}\nstate: {state}\n\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Warp agent run create", environment_id, str(e)), is_error=True
        ))


# ─── Cursor Cloud Agents Handlers ─────────────────────────────────────────────

def _cursor_key() -> str:
    key = (CURSOR_API_KEY or os.getenv("CURSOR_API_KEY", "")).strip()
    if not key:
        raise CursorMcpError(
            "CURSOR_API_KEY not set. Generate at Cursor Dashboard → API Keys, "
            "then add to Doppler project handcraft-mcp / prd."
        )
    return key


def _cursor_request(method: str, path: str, payload: dict | None = None, params: dict | None = None) -> dict | list:
    url = f"{CURSOR_BASE_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {
        "Authorization": f"Bearer {_cursor_key()}",
        "Accept": "application/json",
        "User-Agent": "handcraft-mcp/0.1",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise CursorMcpError(f"Cursor API error {exc.code}: {error_text[:800]}") from exc
    except urllib.error.URLError as exc:
        raise CursorMcpError(f"Cursor connection failed: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CursorMcpError(f"Cursor returned invalid JSON: {exc}") from exc


def _format_cursor_agent_line(agent: dict) -> str:
    agent_id = agent.get("id") or agent.get("agentId") or "—"
    name = agent.get("name") or "—"
    status = agent.get("status") or agent.get("state") or "—"
    url = agent.get("url") or ""
    line = f"[{agent_id}] {name} — {status}"
    if url:
        line += f"\n  {url}"
    return line


def handle_cursor_agents_list(req_id, arguments: dict) -> dict:
    limit = int(arguments.get("limit", 10))
    try:
        data = _cursor_request("GET", "/v1/agents", params={"limit": limit})
        if isinstance(data, dict):
            agents = data.get("items") or data.get("agents")
        else:
            agents = data
        if not isinstance(agents, list):
            agents = []
        if not agents:
            return make_response(req_id, make_tool_text_response("No Cursor agents found."))
        lines = [_format_cursor_agent_line(agent) for agent in agents[:limit]]
        return make_response(req_id, make_tool_text_response(
            f"Cursor agents ({len(lines)}):\n\n" + "\n\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_cursor_agent_get(req_id, arguments: dict) -> dict:
    agent_id = (arguments.get("agent_id") or "").strip()
    if not agent_id:
        return make_response(req_id, make_tool_text_response("Error: agent_id is required", is_error=True))
    try:
        data = _cursor_request("GET", f"/v1/agents/{urllib.parse.quote(agent_id, safe='')}")
        agent = data.get("agent") if isinstance(data, dict) and "agent" in data else data
        lines = [_format_cursor_agent_line(agent if isinstance(agent, dict) else data)]
        latest_run = (agent or {}).get("latestRunId") or (agent or {}).get("latest_run_id")
        if latest_run:
            lines.append(f"latestRunId: {latest_run}")
        return make_response(req_id, make_tool_text_response(
            "\n".join(lines) + "\n\n" + json.dumps(data, ensure_ascii=False, indent=2)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Cursor agent get", agent_id, str(e)), is_error=True
        ))


def handle_cursor_agent_create(req_id, arguments: dict) -> dict:
    prompt = (arguments.get("prompt") or "").strip()
    repo_url = (arguments.get("repo_url") or "").strip()
    branch = (arguments.get("branch") or "").strip()
    name = (arguments.get("name") or "").strip()
    if not prompt:
        return make_response(req_id, make_tool_text_response("Error: prompt is required", is_error=True))
    try:
        payload: dict = {"prompt": {"text": prompt}}
        if name:
            payload["name"] = name[:100]
        if repo_url:
            repo_entry: dict = {"url": repo_url}
            if branch:
                repo_entry["startingRef"] = branch
            payload["repos"] = [repo_entry]
        data = _cursor_request("POST", "/v1/agents", payload=payload)
        agent = data.get("agent") or {}
        run = data.get("run") or {}
        agent_id = agent.get("id") or data.get("id") or "—"
        run_id = run.get("id") or run.get("runId") or "—"
        agent_url = agent.get("url") or ""
        text = f"Cursor agent created.\nagent_id: {agent_id}\nrun_id: {run_id}"
        if agent_url:
            text += f"\nurl: {agent_url}"
        return make_response(req_id, make_tool_text_response(
            text + "\n\n" + json.dumps(data, ensure_ascii=False, indent=2)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Cursor agent create", prompt[:80], str(e)), is_error=True
        ))


def handle_cursor_agent_run_status(req_id, arguments: dict) -> dict:
    agent_id = (arguments.get("agent_id") or "").strip()
    run_id = (arguments.get("run_id") or "").strip()
    if not agent_id or not run_id:
        return make_response(req_id, make_tool_text_response(
            "Error: agent_id and run_id are required", is_error=True
        ))
    try:
        path = f"/v1/agents/{urllib.parse.quote(agent_id, safe='')}/runs/{urllib.parse.quote(run_id, safe='')}"
        data = _cursor_request("GET", path)
        run = data.get("run") if isinstance(data, dict) and "run" in data else data
        state = (run or {}).get("status") or (run or {}).get("state") or "—"
        return make_response(req_id, make_tool_text_response(
            f"Cursor run [{run_id}] state: {state}\n\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Cursor agent run status", f"{agent_id}/{run_id}", str(e)),
            is_error=True,
        ))


# ─── Factory.ai Handlers ──────────────────────────────────────────────────────

def _factory_key() -> str:
    key = (FACTORY_API_KEY or os.getenv("FACTORY_API_KEY", "")).strip()
    if not key:
        raise FactoryMcpError(
            "FACTORY_API_KEY not set. Generate at app.factory.ai/settings/api-keys, "
            "then add to Doppler project handcraft-mcp / prd."
        )
    return key


def _factory_request(
    method: str,
    path: str,
    *,
    base_url: str | None = None,
    payload: dict | None = None,
    params: dict | None = None,
) -> dict | list:
    root = (base_url or FACTORY_API_BASE_URL).rstrip("/")
    url = f"{root}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {
        "Authorization": f"Bearer {_factory_key()}",
        "Accept": "application/json",
        "User-Agent": "handcraft-mcp/0.1",
    }
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise FactoryMcpError(f"Factory API error {exc.code}: {error_text[:800]}") from exc
    except urllib.error.URLError as exc:
        raise FactoryMcpError(f"Factory connection failed: {exc.reason}") from exc

    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FactoryMcpError(f"Factory returned invalid JSON: {exc}") from exc


def _factory_sessions_from_response(data: object) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("sessions", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def handle_factory_sessions_list(req_id, arguments: dict) -> dict:
    limit = int(arguments.get("limit", 10))
    try:
        data = _factory_request("GET", "/api/v0/sessions", params={"limit": limit})
        sessions = _factory_sessions_from_response(data)
        if not sessions:
            return make_response(req_id, make_tool_text_response(
                "No Factory sessions found (feature may require org enablement)."
            ))
        lines = []
        for session in sessions[:limit]:
            sid = session.get("id") or session.get("sessionId") or "—"
            title = session.get("title") or session.get("name") or "—"
            status = session.get("status") or session.get("state") or "—"
            lines.append(f"[{sid}] {title} — {status}")
        return make_response(req_id, make_tool_text_response(
            f"Factory sessions ({len(lines)}):\n\n" + "\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_factory_session_get(req_id, arguments: dict) -> dict:
    session_id = (arguments.get("session_id") or "").strip()
    if not session_id:
        return make_response(req_id, make_tool_text_response("Error: session_id is required", is_error=True))
    try:
        data = _factory_request(
            "GET",
            f"/api/v0/sessions/{urllib.parse.quote(session_id, safe='')}",
        )
        return make_response(req_id, make_tool_json_response(data))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(
            format_safe_mcp_failure("Factory session get", session_id, str(e)), is_error=True
        ))


def handle_factory_computers_list(req_id, arguments: dict) -> dict:  # pylint: disable=unused-argument
    try:
        data = _factory_request("GET", "/api/v0/computers")
        computers = data if isinstance(data, list) else data.get("computers") or data.get("items") or []
        if not computers:
            return make_response(req_id, make_tool_text_response("No Factory computers found."))
        lines = []
        for computer in computers:
            cid = computer.get("id") or "—"
            name = computer.get("name") or "—"
            status = computer.get("status") or computer.get("state") or "—"
            lines.append(f"[{cid}] {name} — {status}")
        return make_response(req_id, make_tool_text_response(
            f"Factory computers ({len(lines)}):\n\n" + "\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


def handle_factory_readiness_reports(req_id, arguments: dict) -> dict:
    limit = int(arguments.get("limit", 10))
    repo_id = (arguments.get("repo_id") or "").strip()
    params: dict = {"limit": limit}
    if repo_id:
        params["repoId"] = repo_id
    try:
        data = _factory_request(
            "GET",
            "/api/organization/maturity-level-reports",
            base_url=FACTORY_APP_BASE_URL,
            params=params,
        )
        reports = data if isinstance(data, list) else data.get("reports") or data.get("items") or []
        if not reports:
            return make_response(req_id, make_tool_text_response("No Factory readiness reports found."))
        lines = []
        for report in reports[:limit]:
            rid = report.get("reportId") or report.get("id") or "—"
            repo = report.get("repoUrl") or report.get("repo_url") or "—"
            created = report.get("createdAt") or report.get("created_at") or ""
            lines.append(f"[{rid}] {repo}" + (f" ({created})" if created else ""))
        return make_response(req_id, make_tool_text_response(
            f"Factory readiness reports ({len(lines)}):\n\n" + "\n".join(lines)
        ))
    except Exception as e:
        return make_response(req_id, make_tool_text_response(f"Error: {e}", is_error=True))


if __name__ == "__main__":
    main()

