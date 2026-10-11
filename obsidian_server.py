"""
obsidian_server.py — WB-11 Vault A Full Cut
Local MCP server for Edgar's Obsidian vault with:
  • Richer truthful provenance: source manifest id + per-file SHA256
  • Real Vault A graph: actual wikilinks [[...]] and resolvable Markdown links [...](...)
  • Durable safe mutation intents: create/update with expected_sha256 conflict semantics
  • Canonical Windows bridge script: applies intents to local Vault A before mirror/QMD sync
  • Safety: rejects traversal/absolute/hidden/control dirs/.obsidian/.trash/non-md
  • No Delete operations

Vault root: G:\Obsidian\Edgar'sObsidianVault (fallback: G:\AgentKB\Obsidian\Edgar'sObsidianVault)

Tools:
  vault_read          - read a note with provenance (manifest_id, sha256, mtime)
  vault_write_intent  - create/update intent with expected_sha256 conflict detection
  vault_apply_intent  - apply a validated intent to canonical local Vault A
  vault_list          - list files/dirs (filtered: .md only, no hidden/control dirs)
  vault_search        - full-text search across .md files
  vault_graph         - get wikilink/markdown link graph for a note or vault
  vault_manifest      - get current vault manifest (all files with sha256)
  vault_bridge        - Windows bridge: apply intents batch to canonical Vault A
"""

import sys
import json
import os
import re
import hashlib
import uuid
from pathlib import Path
from datetime import datetime
from typing import Any
from dataclasses import dataclass, asdict, field

# ── Windows: binary stdin/stdout to avoid CRLF / BOM issues ─────────────────
if sys.platform == "win32":
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(),  os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    sys.stdin  = open(sys.stdin.fileno(),  "r", encoding="utf-8", newline="\n", closefd=False)
    sys.stdout = open(sys.stdout.fileno(), "w", encoding="utf-8", newline="\n", closefd=False)

# ── Constants ────────────────────────────────────────────────────────────────
_VAULT_CANONICAL = Path(r"G:\Obsidian\Edgar'sObsidianVault")
_VAULT_FALLBACK  = Path(r"G:\AgentKB\Obsidian\Edgar'sObsidianVault")
_MANIFEST_ID_FILE = ".vault-manifest-id"
_INTENTS_DIR = ".vault-intents"
_BRIDGE_LOG = "vault-bridge.log"

# Control directories to reject
_CONTROL_DIRS = {".obsidian", ".trash", ".git", ".vault-intents", ".vault-manifest-id", "node_modules", "__pycache__", ".venv"}
_HIDDEN_PREFIX = "."

# Valid file extension
_VALID_EXT = ".md"

# Wikilink pattern: [[page]] or [[page|alias]] or [[page#heading]] or [[page#heading|alias]]
_WIKILINK_RE = re.compile(r'\[\[([^\[\]|\n]+?)(?:\|([^\[\]\n]+?))?(?:#([^\[\]\n]+?))?(?:\|([^\[\]\n]+?))?\]\]')

# Markdown link pattern: [text](path) where path is relative and not a URL
_MD_LINK_RE = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')

# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class FileProvenance:
    """Truthful provenance for a vault file."""
    path: str                    # Relative path from vault root (no .md)
    sha256: str                  # SHA256 of file content
    size: int                    # File size in bytes
    mtime: float                 # Modification time (epoch)
    manifest_id: str             # Current vault manifest ID
    wikilinks: list[str] = field(default_factory=list)   # Outgoing wikilink targets
    mdlinks: list[str] = field(default_factory=list)     # Outgoing markdown link targets
    backlinks: list[str] = field(default_factory=list)   # Incoming links (populated by graph)

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class VaultManifest:
    """Vault-wide manifest with all file provenances."""
    manifest_id: str
    generated_at: float
    file_count: int
    total_size: int
    files: dict[str, FileProvenance]  # key: relative path without .md

    def to_dict(self) -> dict:
        return {
            "manifest_id": self.manifest_id,
            "generated_at": self.generated_at,
            "generated_iso": datetime.fromtimestamp(self.generated_at).isoformat(),
            "file_count": self.file_count,
            "total_size": self.total_size,
            "files": {k: v.to_dict() for k, v in self.files.items()}
        }

@dataclass
class MutationIntent:
    """Durable safe create/update intent with conflict semantics."""
    intent_id: str
    action: str                    # "create" | "update"
    path: str                      # Relative path without .md
    content: str                   # Full markdown content
    expected_sha256: str | None    # For update: current SHA256 to match; None for create
    created_at: float
    created_by: str = "mcp"
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "MutationIntent":
        return cls(**data)

    def content_sha256(self) -> str:
        return hashlib.sha256(self.content.encode("utf-8")).hexdigest()

@dataclass
class IntentResult:
    """Result of applying an intent."""
    intent_id: str
    success: bool
    path: str
    action: str
    old_sha256: str | None
    new_sha256: str
    message: str
    applied_at: float

    def to_dict(self) -> dict:
        return asdict(self)

# ── Vault Root Resolution ────────────────────────────────────────────────────

def _resolve_vault_root() -> Path:
    override = os.getenv("OBSIDIAN_VAULT_ROOT", "").strip()
    if override:
        return Path(override)
    for candidate in (_VAULT_CANONICAL, _VAULT_FALLBACK):
        if candidate.is_dir():
            return candidate
    return _VAULT_CANONICAL

VAULT_ROOT = _resolve_vault_root()
INTENTS_DIR = VAULT_ROOT / _INTENTS_DIR
MANIFEST_ID_FILE = VAULT_ROOT / _MANIFEST_ID_FILE
BRIDGE_LOG_FILE = VAULT_ROOT / _BRIDGE_LOG

# Ensure intents directory exists
INTENTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Helpers ──────────────────────────────────────────────────────────────────

def log(msg: str):
    print(f"[obsidian-mcp] {msg}", file=sys.stderr, flush=True)

def send(obj: dict):
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

def ok(req_id: Any, result: dict):
    send({"jsonrpc": "2.0", "id": req_id, "result": result})

def err(req_id: Any, code: int, msg: str):
    send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": msg}})

def text_result(content: str) -> dict:
    return {"content": [{"type": "text", "text": content}], "isError": False}

def json_result(data: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}], "isError": False}

def _sha256_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _get_manifest_id() -> str:
    """Get or create persistent vault manifest ID."""
    if MANIFEST_ID_FILE.exists():
        try:
            return MANIFEST_ID_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    # Generate new manifest ID
    manifest_id = f"vault-{uuid.uuid4().hex[:12]}"
    MANIFEST_ID_FILE.write_text(manifest_id, encoding="utf-8")
    return manifest_id

def _is_control_or_hidden(rel_path: Path) -> bool:
    """Check if path is in control dirs or hidden."""
    parts = rel_path.parts
    for part in parts:
        if part.startswith(_HIDDEN_PREFIX) or part in _CONTROL_DIRS:
            return True
    return False

def _validate_vault_path(rel: str) -> Path:
    """
    Validate and resolve a relative vault path.
    Rejects: traversal, absolute, hidden, control dirs, non-.md
    Returns: resolved Path inside vault
    """
    if not rel or not isinstance(rel, str):
        raise ValueError("Path must be a non-empty string")

    # Strip leading slashes/backslashes
    rel = rel.lstrip("/\\")

    # Reject absolute paths
    if os.path.isabs(rel):
        raise ValueError(f"Absolute paths not allowed: {rel}")

    # Reject traversal attempts
    if ".." in rel.split("/") or ".." in rel.split("\\"):
        raise ValueError(f"Path traversal not allowed: {rel}")

    # Ensure .md extension
    if not rel.endswith(_VALID_EXT):
        rel = rel + _VALID_EXT

    resolved = (VAULT_ROOT / rel).resolve()
    vault_resolved = VAULT_ROOT.resolve()

    # Ensure within vault
    if not str(resolved).startswith(str(vault_resolved)):
        raise ValueError(f"Path outside vault: {rel}")

    # Check for control/hidden directories in path
    rel_path = resolved.relative_to(vault_resolved)
    if _is_control_or_hidden(rel_path):
        raise ValueError(f"Access to control/hidden directory not allowed: {rel}")

    # Must be .md file
    if resolved.suffix.lower() != _VALID_EXT:
        raise ValueError(f"Only .md files allowed: {rel}")

    return resolved

def _safe_rel_path(path: Path) -> str:
    """Get relative path from vault root without .md extension."""
    return str(path.relative_to(VAULT_ROOT).with_suffix(""))

def _extract_links(content: str) -> tuple[list[str], list[str]]:
    """Extract wikilinks and markdown links from content."""
    wikilinks = []
    mdlinks = []

    # Wikilinks: [[target]] or [[target|alias]] or [[target#heading]]
    for match in _WIKILINK_RE.finditer(content):
        target = match.group(1).strip()
        if target:
            wikilinks.append(target)

    # Markdown links: [text](path)
    for match in _MD_LINK_RE.finditer(content):
        url = match.group(2).strip()
        # Only consider relative paths (not URLs, not anchors only)
        if url and not url.startswith(("http://", "https://", "mailto:", "#", "data:")):
            # Normalize: remove anchor
            url = url.split("#")[0]
            if url:
                mdlinks.append(url)

    return wikilinks, mdlinks

def _resolve_link_target(vault_root: Path, source_path: Path, target: str) -> Path | None:
    """Resolve a wikilink or markdown link target to an actual file."""
    # Wikilink target: can be path-like or just name
    # Try relative to source directory first
    source_dir = source_path.parent

    candidates = [
        source_dir / target,
        vault_root / target,
        vault_root / (target + ".md"),
    ]

    # Also try with .md if not present
    if not target.endswith(".md"):
        candidates.append(source_dir / (target + ".md"))

    for cand in candidates:
        try:
            cand_resolved = cand.resolve()
            if str(cand_resolved).startswith(str(vault_root.resolve())) and cand_resolved.exists():
                # Verify it's not in control/hidden dir
                rel = cand_resolved.relative_to(vault_root.resolve())
                if not _is_control_or_hidden(rel) and cand_resolved.suffix.lower() == ".md":
                    return cand_resolved
        except Exception:
            continue

    return None

# ── Manifest Building ────────────────────────────────────────────────────────

def _build_manifest() -> VaultManifest:
    """Build complete vault manifest with provenance for all .md files."""
    manifest_id = _get_manifest_id()
    files: dict[str, FileProvenance] = {}
    all_wikilinks: dict[str, list[str]] = {}  # source -> targets
    all_mdlinks: dict[str, list[str]] = {}

    # First pass: collect all files and their outgoing links
    for md_file in VAULT_ROOT.rglob("*.md"):
        # Skip hidden/control dirs
        try:
            rel = md_file.relative_to(VAULT_ROOT)
        except ValueError:
            continue
        if _is_control_or_hidden(rel):
            continue

        rel_key = str(rel.with_suffix(""))
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        stat = md_file.stat()
        sha256 = _sha256_of_file(md_file)
        wikilinks, mdlinks = _extract_links(content)

        all_wikilinks[rel_key] = wikilinks
        all_mdlinks[rel_key] = mdlinks

        files[rel_key] = FileProvenance(
            path=rel_key,
            sha256=sha256,
            size=stat.st_size,
            mtime=stat.st_mtime,
            manifest_id=manifest_id,
            wikilinks=wikilinks,
            mdlinks=mdlinks,
            backlinks=[]  # Will populate in second pass
        )

    # Second pass: resolve links and build backlinks
    # Build a map of all possible targets (wikilink targets can be just names)
    path_by_name: dict[str, str] = {}  # name -> rel_key
    path_by_stem: dict[str, str] = {}  # stem -> rel_key
    for rel_key in files:
        stem = Path(rel_key).name
        path_by_name[rel_key] = rel_key
        path_by_stem[stem] = rel_key

    # Resolve links and build backlinks
    for source_key, provenance in files.items():
        source_path = VAULT_ROOT / (source_key + ".md")
        backlinks = []

        # Resolve wikilinks
        for target in provenance.wikilinks:
            resolved = _resolve_link_target(VAULT_ROOT, source_path, target)
            if resolved:
                target_key = _safe_rel_path(resolved)
                if target_key in files:
                    files[target_key].backlinks.append(source_key)

        # Resolve markdown links
        for target in provenance.mdlinks:
            resolved = _resolve_link_target(VAULT_ROOT, source_path, target)
            if resolved:
                target_key = _safe_rel_path(resolved)
                if target_key in files:
                    files[target_key].backlinks.append(source_key)

    # Deduplicate backlinks
    for prov in files.values():
        prov.backlinks = sorted(set(prov.backlinks))

    total_size = sum(f.size for f in files.values())
    return VaultManifest(
        manifest_id=manifest_id,
        generated_at=datetime.now().timestamp(),
        file_count=len(files),
        total_size=total_size,
        files=files
    )

# ── Tool Implementations ─────────────────────────────────────────────────────

def tool_vault_read(args: dict) -> dict:
    """Read a note with full provenance."""
    path = _validate_vault_path(args["path"])
    if not path.exists():
        return text_result(f"Note not found: {args['path']}")

    content = path.read_text(encoding="utf-8")
    stat = path.stat()
    sha256 = _sha256_of_file(path)
    wikilinks, mdlinks = _extract_links(content)
    rel_key = _safe_rel_path(path)
    manifest_id = _get_manifest_id()

    # Get backlinks by checking manifest (rebuild if needed)
    backlinks = []
    # Quick scan for backlinks (could be optimized with cached manifest)
    for md_file in VAULT_ROOT.rglob("*.md"):
        try:
            rel = md_file.relative_to(VAULT_ROOT)
        except ValueError:
            continue
        if _is_control_or_hidden(rel):
            continue
        try:
            other_content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        other_wikilinks, other_mdlinks = _extract_links(other_content)
        # Check if this file is linked
        target_variants = [rel_key, path.stem]
        if any(t in other_wikilinks for t in target_variants) or any(t in other_mdlinks for t in target_variants):
            backlinks.append(_safe_rel_path(md_file))

    provenance = FileProvenance(
        path=rel_key,
        sha256=sha256,
        size=stat.st_size,
        mtime=stat.st_mtime,
        manifest_id=manifest_id,
        wikilinks=wikilinks,
        mdlinks=mdlinks,
        backlinks=sorted(set(backlinks))
    )

    return json_result({
        "content": content,
        "provenance": provenance.to_dict()
    })

def tool_vault_write_intent(args: dict) -> dict:
    """
    Create a mutation intent (create or update) with expected_sha256 conflict semantics.
    Does NOT write to vault directly — creates intent file for bridge to apply.
    """
    action = args.get("action", "").strip().lower()
    if action not in ("create", "update"):
        return text_result("Action must be 'create' or 'update'")

    path = _validate_vault_path(args["path"])
    content = args.get("content", "")
    if not isinstance(content, str):
        return text_result("Content must be a string")

    expected_sha256 = args.get("expected_sha256")
    if expected_sha256 is not None and not isinstance(expected_sha256, str):
        return text_result("expected_sha256 must be a string or null")

    rel_key = _safe_rel_path(path)

    # For update: verify current file matches expected_sha256
    if action == "update":
        if not path.exists():
            return text_result(f"Cannot update: note not found: {rel_key}")
        if expected_sha256 is None:
            return text_result("Update requires expected_sha256 for conflict detection")
        current_sha256 = _sha256_of_file(path)
        if current_sha256 != expected_sha256:
            return text_result(
                f"Conflict: current SHA256 ({current_sha256[:16]}...) "
                f"does not match expected ({expected_sha256[:16]}...). "
                f"Read the note first to get current provenance."
            )
    else:  # create
        if path.exists():
            return text_result(f"Cannot create: note already exists: {rel_key}. Use update instead.")
        if expected_sha256 is not None:
            return text_result("Create should not provide expected_sha256")

    # Create intent
    intent = MutationIntent(
        intent_id=f"intent-{uuid.uuid4().hex[:12]}",
        action=action,
        path=rel_key,
        content=content,
        expected_sha256=expected_sha256,
        created_at=datetime.now().timestamp(),
        created_by="mcp",
        metadata=args.get("metadata", {})
    )

    # Save intent file
    intent_file = INTENTS_DIR / f"{intent.intent_id}.json"
    intent_file.write_text(json.dumps(intent.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    return json_result({
        "intent_id": intent.intent_id,
        "action": action,
        "path": rel_key,
        "content_sha256": intent.content_sha256(),
        "expected_sha256": expected_sha256,
        "status": "pending",
        "message": f"Intent created. Apply with vault_apply_intent or vault_bridge.",
        "intent_file": str(intent_file.relative_to(VAULT_ROOT))
    })

def tool_vault_apply_intent(args: dict) -> dict:
    """Apply a single validated intent to canonical local Vault A."""
    intent_id = args.get("intent_id", "").strip()
    if not intent_id:
        return text_result("intent_id required")

    intent_file = INTENTS_DIR / f"{intent_id}.json"
    if not intent_file.exists():
        return text_result(f"Intent not found: {intent_id}")

    try:
        intent_data = json.loads(intent_file.read_text(encoding="utf-8"))
        intent = MutationIntent.from_dict(intent_data)
    except Exception as e:
        return text_result(f"Invalid intent file: {e}")

    path = VAULT_ROOT / (intent.path + ".md")

    # Re-validate conflict for update
    if intent.action == "update":
        if not path.exists():
            result = IntentResult(
                intent_id=intent.intent_id,
                success=False,
                path=intent.path,
                action="update",
                old_sha256=None,
                new_sha256="",
                message="Note no longer exists",
                applied_at=datetime.now().timestamp()
            )
            return json_result(result.to_dict())

        current_sha256 = _sha256_of_file(path)
        if intent.expected_sha256 and current_sha256 != intent.expected_sha256:
            result = IntentResult(
                intent_id=intent.intent_id,
                success=False,
                path=intent.path,
                action="update",
                old_sha256=current_sha256,
                new_sha256="",
                message=f"Conflict: current SHA256 ({current_sha256[:16]}...) != expected ({intent.expected_sha256[:16]}...)",
                applied_at=datetime.now().timestamp()
            )
            return json_result(result.to_dict())

        old_sha256 = current_sha256
    else:
        old_sha256 = None

    # Apply the intent
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(intent.content, encoding="utf-8")
    new_sha256 = _sha256_of_file(path)

    # Remove intent file on success
    intent_file.unlink(missing_ok=True)

    result = IntentResult(
        intent_id=intent.intent_id,
        success=True,
        path=intent.path,
        action=intent.action,
        old_sha256=old_sha256,
        new_sha256=new_sha256,
        message=f"{intent.action.capitalize()}d: {intent.path}",
        applied_at=datetime.now().timestamp()
    )
    return json_result(result.to_dict())

def tool_vault_list(args: dict) -> dict:
    """List .md files and subdirectories (filtered: no hidden/control dirs, .md only)."""
    folder = args.get("folder", "")
    folder = folder.lstrip("/\\")
    target = (VAULT_ROOT / folder).resolve()
    vault_resolved = VAULT_ROOT.resolve()

    if not str(target).startswith(str(vault_resolved)):
        return text_result("Invalid folder path")

    if not target.exists():
        return text_result(f"Folder not found: {folder or '(root)'}")

    lines = []
    for item in sorted(target.iterdir()):
        try:
            rel = item.relative_to(vault_resolved)
        except ValueError:
            continue

        # Skip hidden/control dirs
        if _is_control_or_hidden(rel):
            continue

        if item.is_dir():
            lines.append(f"📁 {rel}/")
        elif item.suffix.lower() == _VALID_EXT:
            lines.append(f"📄 {rel}")

    if not lines:
        return text_result(f"Empty: {folder or '(root)'}")
    return text_result("\n".join(lines))

def tool_vault_search(args: dict) -> dict:
    """Full-text search across .md files (filtered)."""
    query = args.get("query", "").lower()
    max_results = int(args.get("max_results", 20))

    if not query:
        return text_result("Query required")

    hits = []
    for md_file in VAULT_ROOT.rglob("*.md"):
        try:
            rel = md_file.relative_to(VAULT_ROOT)
        except ValueError:
            continue
        if _is_control_or_hidden(rel):
            continue

        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        if query in content.lower() or query in md_file.name.lower():
            matching_lines = []
            for i, line in enumerate(content.splitlines()):
                if query in line.lower():
                    matching_lines.append(f"  L{i+1}: {line.strip()[:100]}")
                if len(matching_lines) >= 3:
                    break

            rel_key = _safe_rel_path(md_file)
            hits.append(f"[[{rel_key}]]")
            if matching_lines:
                hits.extend(matching_lines)
            hits.append("")

        if len(hits) >= max_results * 5:
            break

    if not hits:
        return text_result(f'No results for "{query}"')
    return text_result(f'Results for "{query}":\n\n' + "\n".join(hits))

def tool_vault_graph(args: dict) -> dict:
    """Get wikilink/markdown link graph for a note or entire vault."""
    scope = args.get("scope", "vault").strip().lower()
    path = args.get("path")

    manifest = _build_manifest()

    if scope == "note" and path:
        # Single note graph
        validated = _validate_vault_path(path)
        rel_key = _safe_rel_path(validated)
        if rel_key not in manifest.files:
            return text_result(f"Note not found: {rel_key}")

        prov = manifest.files[rel_key]
        return json_result({
            "scope": "note",
            "path": rel_key,
            "outgoing_wikilinks": prov.wikilinks,
            "outgoing_mdlinks": prov.mdlinks,
            "incoming_backlinks": prov.backlinks,
            "provenance": prov.to_dict()
        })

    # Full vault graph
    nodes = []
    edges = []

    for rel_key, prov in manifest.files.items():
        nodes.append({
            "id": rel_key,
            "sha256": prov.sha256[:16] + "...",
            "size": prov.size
        })
        for target in prov.wikilinks:
            resolved = _resolve_link_target(VAULT_ROOT, VAULT_ROOT / (rel_key + ".md"), target)
            if resolved:
                target_key = _safe_rel_path(resolved)
                if target_key in manifest.files:
                    edges.append({"source": rel_key, "target": target_key, "type": "wikilink"})
        for target in prov.mdlinks:
            resolved = _resolve_link_target(VAULT_ROOT, VAULT_ROOT / (rel_key + ".md"), target)
            if resolved:
                target_key = _safe_rel_path(resolved)
                if target_key in manifest.files:
                    edges.append({"source": rel_key, "target": target_key, "type": "mdlink"})

    return json_result({
        "scope": "vault",
        "manifest_id": manifest.manifest_id,
        "generated_at": manifest.generated_at,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges
    })

def tool_vault_manifest(args: dict) -> dict:
    """Get current vault manifest (all files with sha256)."""
    include_content = args.get("include_content", False)
    manifest = _build_manifest()

    if include_content:
        # Include full provenance for each file
        return json_result(manifest.to_dict())
    else:
        # Lightweight: just path, sha256, size, mtime
        files_light = {
            k: {
                "sha256": v.sha256,
                "size": v.size,
                "mtime": v.mtime,
                "wikilink_count": len(v.wikilinks),
                "mdlink_count": len(v.mdlinks),
                "backlink_count": len(v.backlinks)
            }
            for k, v in manifest.files.items()
        }
        return json_result({
            "manifest_id": manifest.manifest_id,
            "generated_at": manifest.generated_at,
            "generated_iso": datetime.fromtimestamp(manifest.generated_at).isoformat(),
            "file_count": manifest.file_count,
            "total_size": manifest.total_size,
            "files": files_light
        })

def tool_vault_bridge(args: dict) -> dict:
    """
    Canonical Windows bridge: apply pending intents to canonical local Vault A.
    This is the ONLY canonical write path — VPS mirror/QMD sync must pull from here.
    """
    dry_run = args.get("dry_run", False)
    intent_ids = args.get("intent_ids")  # Optional: specific intents to apply

    # Collect pending intents
    intent_files = sorted(INTENTS_DIR.glob("*.json"))
    if intent_ids:
        intent_files = [INTENTS_DIR / f"{iid}.json" for iid in intent_ids if (INTENTS_DIR / f"{iid}.json").exists()]

    if not intent_files:
        return json_result({
            "applied": 0,
            "failed": 0,
            "skipped": 0,
            "results": [],
            "message": "No pending intents"
        })

    results = []
    applied = 0
    failed = 0
    skipped = 0

    for intent_file in intent_files:
        try:
            intent_data = json.loads(intent_file.read_text(encoding="utf-8"))
            intent = MutationIntent.from_dict(intent_data)
        except Exception as e:
            results.append({
                "intent_id": intent_file.stem,
                "success": False,
                "message": f"Invalid intent file: {e}"
            })
            failed += 1
            continue

        path = VAULT_ROOT / (intent.path + ".md")

        # Re-validate for update
        if intent.action == "update":
            if not path.exists():
                results.append({
                    "intent_id": intent.intent_id,
                    "success": False,
                    "path": intent.path,
                    "action": "update",
                    "message": "Note no longer exists"
                })
                failed += 1
                continue

            current_sha256 = _sha256_of_file(path)
            if intent.expected_sha256 and current_sha256 != intent.expected_sha256:
                results.append({
                    "intent_id": intent.intent_id,
                    "success": False,
                    "path": intent.path,
                    "action": "update",
                    "old_sha256": current_sha256,
                    "message": f"Conflict: current SHA256 != expected"
                })
                failed += 1
                continue

            old_sha256 = current_sha256
        else:
            old_sha256 = None

        if dry_run:
            results.append({
                "intent_id": intent.intent_id,
                "success": True,
                "path": intent.path,
                "action": intent.action,
                "old_sha256": old_sha256,
                "new_sha256": intent.content_sha256(),
                "message": f"[DRY RUN] Would {intent.action}: {intent.path}"
            })
            skipped += 1
            continue

        # Apply
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(intent.content, encoding="utf-8")
        new_sha256 = _sha256_of_file(path)

        # Remove intent file
        intent_file.unlink(missing_ok=True)

        # Log to bridge log
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "intent_id": intent.intent_id,
            "action": intent.action,
            "path": intent.path,
            "old_sha256": old_sha256,
            "new_sha256": new_sha256
        }
        try:
            with BRIDGE_LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

        results.append({
            "intent_id": intent.intent_id,
            "success": True,
            "path": intent.path,
            "action": intent.action,
            "old_sha256": old_sha256,
            "new_sha256": new_sha256,
            "message": f"{intent.action.capitalize()}d: {intent.path}"
        })
        applied += 1

    return json_result({
        "applied": applied,
        "failed": failed,
        "skipped": skipped,
        "total": len(intent_files),
        "dry_run": dry_run,
        "results": results,
        "message": f"Bridge complete: {applied} applied, {failed} failed, {skipped} skipped"
    })

# ── Tool Registry ────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "vault_read",
        "description": "Read a note from the Obsidian vault by relative path. Returns content + full provenance (manifest_id, sha256, size, mtime, wikilinks, mdlinks, backlinks). .md auto-appended.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative path to note inside vault (without .md)"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "vault_write_intent",
        "description": "Create a mutation intent (create/update) with expected_sha256 conflict semantics. Does NOT write directly — creates intent file for bridge to apply. For update: must provide expected_sha256 from current provenance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["create", "update"], "description": "create or update"},
                "path": {"type": "string", "description": "Relative path (without .md)"},
                "content": {"type": "string", "description": "Full markdown content"},
                "expected_sha256": {"type": "string", "description": "Required for update: current SHA256 to match for conflict detection"},
                "metadata": {"type": "object", "description": "Optional metadata"}
            },
            "required": ["action", "path", "content"]
        }
    },
    {
        "name": "vault_apply_intent",
        "description": "Apply a single validated intent to canonical local Vault A. Re-validates expected_sha256 at apply time. Removes intent file on success.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "intent_id": {"type": "string", "description": "Intent ID from vault_write_intent"}
            },
            "required": ["intent_id"]
        }
    },
    {
        "name": "vault_list",
        "description": "List .md files and subdirectories in a vault folder. Filters out hidden dirs, control dirs (.obsidian, .trash, .git, etc.), and non-.md files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder": {"type": "string", "description": "Relative folder path. Omit or empty for vault root."}
            },
            "required": []
        }
    },
    {
        "name": "vault_search",
        "description": "Full-text search across all .md files in the vault (filtered: no hidden/control dirs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 20}
            },
            "required": ["query"]
        }
    },
    {
        "name": "vault_graph",
        "description": "Get wikilink/markdown link graph. Scope 'note' returns graph for one note (outgoing/incoming links). Scope 'vault' returns full vault graph with nodes and edges.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["note", "vault"], "default": "vault"},
                "path": {"type": "string", "description": "Required for scope=note: relative path to note"}
            },
            "required": []
        }
    },
    {
        "name": "vault_manifest",
        "description": "Get current vault manifest with all files' provenance (sha256, size, mtime, link counts). Set include_content=true for full provenance per file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_content": {"type": "boolean", "default": False}
            },
            "required": []
        }
    },
    {
        "name": "vault_bridge",
        "description": "Canonical Windows bridge: apply pending intents to canonical local Vault A. This is the ONLY canonical write path — VPS mirror/QMD sync must pull from here. Supports dry_run.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "dry_run": {"type": "boolean", "default": False, "description": "Validate and preview without applying"},
                "intent_ids": {"type": "array", "items": {"type": "string"}, "description": "Optional: specific intent IDs to apply"}
            },
            "required": []
        }
    }
]

TOOL_HANDLERS = {
    "vault_read": tool_vault_read,
    "vault_write_intent": tool_vault_write_intent,
    "vault_apply_intent": tool_vault_apply_intent,
    "vault_list": tool_vault_list,
    "vault_search": tool_vault_search,
    "vault_graph": tool_vault_graph,
    "vault_manifest": tool_vault_manifest,
    "vault_bridge": tool_vault_bridge,
}

# ── MCP Request Router ────────────────────────────────────────────────────────

def handle(msg: dict):
    method = msg.get("method", "")
    req_id = msg.get("id")
    log(f"← {method}")

    if method == "initialize":
        ok(req_id, {
            "protocolVersion": "2025-11-25",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "obsidian-vault-a", "version": "2.0.0-wb11"}
        })
    elif method == "tools/list":
        ok(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        name = msg.get("params", {}).get("name", "")
        args = msg.get("params", {}).get("arguments", {})
        handler = TOOL_HANDLERS.get(name)
        if handler:
            try:
                result = handler(args)
                ok(req_id, result)
            except Exception as e:
                ok(req_id, {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True})
        else:
            err(req_id, -32601, f"Tool not found: {name}")
    elif method == "ping":
        ok(req_id, {})
    elif msg.get("jsonrpc") and "id" not in msg:
        pass  # notification
    else:
        if req_id is not None:
            err(req_id, -32601, f"Method not found: {method}")

def main():
    log(f"Obsidian Vault A MCP ready — vault: {VAULT_ROOT}")
    log(f"Manifest ID: {_get_manifest_id()}")
    log(f"Intents dir: {INTENTS_DIR}")
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            msg = json.loads(raw_line)
            handle(msg)
        except json.JSONDecodeError as e:
            log(f"JSON parse error: {e}")

if __name__ == "__main__":
    main()