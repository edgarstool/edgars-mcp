#!/usr/bin/env python3
"""
WB-11 Vault A Bridge — Python implementation (cross-platform)
Canonical write path for Vault A mutations.
Applies mutation intents to canonical local Vault A before mirror/QMD sync.

Usage:
    python vault_bridge.py [--vault-root PATH] [--dry-run] [--intent-ids ID1,ID2] [--verbose]
"""

import sys
import json
import os
import argparse
from pathlib import Path
from datetime import datetime
import hashlib

# ── Constants ────────────────────────────────────────────────────────────────
INTENTS_DIR_NAME = ".vault-intents"
MANIFEST_ID_FILE = ".vault-manifest-id"
BRIDGE_LOG_FILE = "vault-bridge.log"
VALID_EXT = ".md"

CONTROL_DIRS = {
    ".obsidian", ".trash", ".git", ".vault-intents",
    ".vault-manifest-id", "node_modules", "__pycache__", ".venv"
}
HIDDEN_PREFIX = "."

# ── Helpers ──────────────────────────────────────────────────────────────────

def log(msg: str, level: str = "INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {msg}"
    print(line, flush=True)
    # Also append to bridge log file
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": msg
    }
    try:
        with open(VAULT_ROOT / BRIDGE_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

def vlog(msg: str):
    if VERBOSE:
        log(msg, "VERBOSE")

def is_control_or_hidden(rel_path: Path) -> bool:
    parts = rel_path.parts
    for part in parts:
        if part.startswith(HIDDEN_PREFIX) or part in CONTROL_DIRS:
            return True
    return False

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def sha256_string(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def resolve_vault_path(rel: str) -> Path:
    if not rel or not isinstance(rel, str):
        raise ValueError("Path must be a non-empty string")
    rel = rel.lstrip("/\\")
    if os.path.isabs(rel):
        raise ValueError(f"Absolute paths not allowed: {rel}")
    if ".." in rel.split("/") or ".." in rel.split("\\"):
        raise ValueError(f"Path traversal not allowed: {rel}")
    if not rel.lower().endswith(VALID_EXT):
        rel += VALID_EXT

    resolved = (VAULT_ROOT / rel).resolve()
    vault_resolved = VAULT_ROOT.resolve()

    if not str(resolved).startswith(str(vault_resolved)):
        raise ValueError(f"Path outside vault: {rel}")

    rel_path = resolved.relative_to(vault_resolved)
    if is_control_or_hidden(rel_path):
        raise ValueError(f"Access to control/hidden directory not allowed: {rel}")

    if resolved.suffix.lower() != VALID_EXT:
        raise ValueError(f"Only .md files allowed: {rel}")

    return resolved

def safe_rel_path(path: Path) -> str:
    return str(path.relative_to(VAULT_ROOT).with_suffix(""))

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global VAULT_ROOT, VERBOSE

    parser = argparse.ArgumentParser(description="WB-11 Vault A Bridge")
    parser.add_argument("--vault-root", default=r"G:\Obsidian\Edgar'sObsidianVault",
                        help="Canonical Vault A root path")
    parser.add_argument("--dry-run", action="store_true", help="Validate and preview without applying")
    parser.add_argument("--intent-ids", help="Comma-separated intent IDs to apply")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    args = parser.parse_args()

    VAULT_ROOT = Path(args.vault_root).resolve()
    VERBOSE = args.verbose
    DRY_RUN = args.dry_run

    log("=== Vault A Bridge Started ===")
    log(f"Vault Root: {VAULT_ROOT}")
    log(f"Dry Run: {DRY_RUN}")

    intents_dir = VAULT_ROOT / INTENTS_DIR_NAME
    if not intents_dir.exists():
        log(f"Intents directory does not exist: {intents_dir}", "WARN")
        log("=== Vault A Bridge Complete: 0 applied ===")
        return 0

    intent_files = sorted(intents_dir.glob("*.json"))
    if args.intent_ids:
        selected = set(i.strip() for i in args.intent_ids.split(",") if i.strip())
        intent_files = [f for f in intent_files if f.stem in selected]

    if not intent_files:
        log("No matching intent files found")
        log("=== Vault A Bridge Complete: 0 applied ===")
        return 0

    applied = 0
    failed = 0
    skipped = 0
    results = []

    for intent_file in intent_files:
        intent_id = intent_file.stem
        vlog(f"Processing intent: {intent_id}")

        try:
            intent_data = json.loads(intent_file.read_text(encoding="utf-8"))

            # Validate
            required = ["intent_id", "action", "path", "content"]
            for field in required:
                if field not in intent_data:
                    raise ValueError(f"Missing required field: {field}")
            if intent_data["action"] not in ("create", "update"):
                raise ValueError(f"Invalid action: {intent_data['action']}")

            target_path = resolve_vault_path(intent_data["path"])
            rel_path = safe_rel_path(target_path)

            old_sha256 = None
            if intent_data["action"] == "update":
                if not target_path.exists():
                    raise ValueError(f"Note no longer exists: {rel_path}")
                expected = intent_data.get("expected_sha256")
                if expected:
                    current = sha256_file(target_path)
                    if current != expected:
                        raise ValueError(f"Conflict: current SHA256 ({current[:16]}...) != expected ({expected[:16]}...)")
                old_sha256 = sha256_file(target_path)
            else:
                if target_path.exists():
                    raise ValueError(f"Cannot create: note already exists: {rel_path}")

            new_sha256 = sha256_string(intent_data["content"])

            if DRY_RUN:
                result = {
                    "intent_id": intent_id,
                    "success": True,
                    "path": rel_path,
                    "action": intent_data["action"],
                    "old_sha256": old_sha256,
                    "new_sha256": new_sha256,
                    "message": f"[DRY RUN] Would {intent_data['action']}: {rel_path}"
                }
                results.append(result)
                skipped += 1
                log(f"[DRY RUN] {intent_data['action']} {rel_path}")
                continue

            # Apply
            target_path.parent.mkdir(parents=True, exist_ok=True)
            # Write bytes directly to avoid trailing newline
            target_path.write_bytes(intent_data["content"].encode("utf-8"))

            # Verify
            verify_sha256 = sha256_file(target_path)
            if verify_sha256 != new_sha256:
                raise ValueError("Write verification failed: SHA256 mismatch after write")

            # Remove intent file
            intent_file.unlink(missing_ok=True)

            # Log to bridge log (JSONL)
            log_entry = {
                "timestamp": datetime.now().isoformat(),
                "intent_id": intent_id,
                "action": intent_data["action"],
                "path": rel_path,
                "old_sha256": old_sha256,
                "new_sha256": new_sha256
            }
            try:
                with open(VAULT_ROOT / BRIDGE_LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

            result = {
                "intent_id": intent_id,
                "success": True,
                "path": rel_path,
                "action": intent_data["action"],
                "old_sha256": old_sha256,
                "new_sha256": new_sha256,
                "message": f"{intent_data['action']} {rel_path}"
            }
            results.append(result)
            applied += 1
            log(f"Applied: {intent_data['action']} {rel_path}")

        except Exception as e:
            result = {
                "intent_id": intent_id,
                "success": False,
                "message": str(e)
            }
            results.append(result)
            failed += 1
            log(f"FAILED {intent_id}: {e}", "ERROR")

    summary = {
        "applied": applied,
        "failed": failed,
        "skipped": skipped,
        "total": len(intent_files),
        "dry_run": DRY_RUN,
        "results": results,
        "timestamp": datetime.now().isoformat()
    }

    log("=== Vault A Bridge Complete ===")
    log(f"Applied: {applied}, Failed: {failed}, Skipped: {skipped}")
    log(f"Summary: {json.dumps(summary, ensure_ascii=False)}")

    # Output JSON to stdout
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if failed > 0 else 0

if __name__ == "__main__":
    sys.exit(main())