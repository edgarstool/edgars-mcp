"""TrackTW 輪詢器 — 把 track.tw 沒有 webhook 的限制用本機 polling 補上。

設計：
  - 每 20 分鐘跑一輪（可由 env TRACKTW_POLLER_INTERVAL_SEC 覆寫）
  - 讀 config/tracktw_watchlist.json（想追哪些單）
  - 對每單 import → tracking → 比對快照（hash of events）
  - 有變化 → POST 到 HOOKS_EDGARS_TOOLS_TRACKTW（HMAC 簽名可選）
  - 快照存 G:/AI_WORK_512/cache/tracktw_poller/state.json

Secrets（由 Doppler 注入，不要寫在程式裡）：
  TRACKTW_API_KEY              — track.tw API Bearer
  HOOKS_EDGARS_TOOLS_URL       — 例如 https://hooks.edgars.tools/tracktw
  HOOKS_EDGARS_TOOLS_TOKEN     — 對接 hook 的 HMAC secret（可選）
  TRACKTW_POLLER_INTERVAL_SEC  — 預設 1200（20 分鐘）

執行：
  python tracktw_poller.py once     # 跑一輪立即退出（debug / 驗證）
  python tracktw_poller.py loop     # 持續跑，每輪 sleep interval
  python tracktw_poller.py status   # 看快照狀態

排程（Windows Task Scheduler）：
  scripts/run-tracktw-poller.cmd loop
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# ── 設定 ──────────────────────────────────────────────────────────────────────
TRACKTW_BASE_URL = os.getenv("TRACKTW_BASE_URL", "https://track.tw/api/v1").rstrip("/")
TRACKTW_API_KEY  = os.getenv("TRACKTW_API_KEY", "").strip()
HOOKS_URL        = os.getenv("HOOKS_EDGARS_TOOLS_URL", "https://hooks.edgars.tools/tracktw").strip()
HOOKS_TOKEN      = os.getenv("HOOKS_EDGARS_TOOLS_TOKEN", "").strip()
POLL_INTERVAL    = int(os.getenv("TRACKTW_POLLER_INTERVAL_SEC", "1200"))

# Snapshot 在 runtime root（G:\AI_WORK_512 是 EDGAR-OS canonical runtime/cache）
STATE_DIR = Path(os.getenv("TRACKTW_POLLER_STATE_DIR",
                           r"G:\AI_WORK_512\cache\tracktw_poller"))
STATE_FILE = STATE_DIR / "state.json"
LOG_FILE   = STATE_DIR / "poller.log"

# watchlist 在 repo 內，編輯這個檔加入想追的單
REPO_ROOT   = Path(__file__).resolve().parent
WATCHLIST   = REPO_ROOT / "config" / "tracktw_watchlist.json"

# 預設併發：對 track.tw 的 import + tracking 對單一單都是 sequential；
# 不同單之間可並行。watchlist < 50 時 workers=4 已足。
PARALLEL_WORKERS = int(os.getenv("TRACKTW_POLLER_PARALLEL", "4"))

logging.basicConfig(
    level=os.getenv("TRACKTW_POLLER_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("tracktw_poller")


# ── 資料結構 ──────────────────────────────────────────────────────────────────
@dataclass
class WatchEntry:
    """watchlist.json 的一筆追蹤項。"""
    tracking_number: str
    carrier_name: str        # 例如 "7-Eleven店到店"、"黑貓"
    label: str = ""          # 自訂給人類看的標籤（optional）
    carrier_id: str = ""     # cache 起來避免每次重抓


@dataclass
class PackageSnapshot:
    """某一單的最新事件快照。"""
    tracking_number: str
    carrier_name: str
    carrier_id: str
    label: str
    package_uuid: str
    last_state: str = ""
    last_event_count: int = 0
    last_event_hash: str = ""     # hash(events) 用於偵測變化
    last_checked_at: str = ""
    last_changed_at: str = ""
    error: str = ""


# ── State I/O ─────────────────────────────────────────────────────────────────
def load_state() -> dict[str, PackageSnapshot]:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        out: dict[str, PackageSnapshot] = {}
        for k, v in data.items():
            out[k] = PackageSnapshot(**v)
        return out
    except Exception as exc:
        log.warning("state.json 讀取失敗，重新建立: %s", exc)
        return {}


def save_state(state: dict[str, PackageSnapshot]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({k: asdict(v) for k, v in state.items()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(STATE_FILE)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── track.tw API ──────────────────────────────────────────────────────────────
def _tracktw_request(method: str, path: str,
                      payload: Optional[dict] = None,
                      params: Optional[dict] = None) -> Any:
    if not TRACKTW_API_KEY:
        raise RuntimeError("TRACKTW_API_KEY not set")

    url = f"{TRACKTW_BASE_URL}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    headers = {
        "Authorization": f"Bearer {TRACKTW_API_KEY}",
        "Accept": "application/json",
        "User-Agent": "edgars-tracktw-poller/1.0",
    }
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"track.tw HTTP {exc.code}: {text[:300]}") from exc


def _carrier_id_cache() -> dict[str, str]:
    """name → id 的 mapping。"""
    data = _tracktw_request("GET", "/carrier/available")
    if not isinstance(data, list):
        return {}
    return {
        str(c.get("name", "")).strip(): str(c.get("id", "")).strip()
        for c in data
        if c.get("name") and c.get("id")
    }


def _find_carrier_id(carrier_name: str, cache: dict[str, str]) -> str:
    """直接從 cache 找（名稱完全相符），找不到再 fallback substring。"""
    name = carrier_name.strip()
    if name in cache:
        return cache[name]
    # substring fallback（多語系承運商常見）
    for k, v in cache.items():
        if name in k or k in name:
            return v
    raise ValueError(f"找不到承運商：{carrier_name}")


def _import_package(carrier_id: str, tracking_number: str) -> str:
    """回 package_uuid。對同一單 import 是冪等的（會回同一個 UUID）。"""
    tn = tracking_number.strip().upper()
    data = _tracktw_request("POST", "/package/import", payload={
        "carrier_id": carrier_id,
        "tracking_number": [tn],
        "notify_state": "inactive",   # 我們自己 polling，不需要 server 推
    })
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected import response: {data}")
    uuid_ = data.get(tn) or data.get(tn.upper()) or data.get(tracking_number)
    if not uuid_:
        raise RuntimeError(f"import 無 uuid：{data}")
    return str(uuid_)


def _track_package(package_uuid: str) -> dict:
    return _tracktw_request("GET", f"/package/tracking/{package_uuid}")


def _summarize_events(data: dict) -> tuple[str, int, str]:
    """回 (latest_state, event_count, event_hash)。"""
    events = data.get("events") or data.get("tracking") or []
    if not isinstance(events, list):
        return ("", 0, "")
    event_count = len(events)
    latest_state = ""
    if events and isinstance(events[-1], dict):
        latest_state = str(events[-1].get("state") or events[-1].get("status") or "")
    blob = json.dumps(events, ensure_ascii=False, sort_keys=True).encode("utf-8")
    event_hash = hashlib.sha256(blob).hexdigest()
    return (latest_state, event_count, event_hash)


# ── Hooks 推送 ────────────────────────────────────────────────────────────────
def _sign(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256)
    return "sha256=" + mac.hexdigest()


def post_to_hook(snap: PackageSnapshot, prev: Optional[PackageSnapshot]) -> dict:
    """POST 到 hooks.edgars.tools/tracktw。回 server response。"""
    payload = {
        "event": "package.changed",
        "tracking_number": snap.tracking_number,
        "carrier_name": snap.carrier_name,
        "carrier_id": snap.carrier_id,
        "label": snap.label,
        "package_uuid": snap.package_uuid,
        "latest_state": snap.last_state,
        "event_count": snap.last_event_count,
        "observed_at": now_iso(),
        "previous": (
            {
                "latest_state": prev.last_state,
                "event_count": prev.last_event_count,
                "last_event_hash": prev.last_event_hash,
                "last_checked_at": prev.last_checked_at,
            } if prev else None
        ),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if HOOKS_TOKEN:
        headers["X-TrackTW-Webhook-Signature"] = _sign(body, HOOKS_TOKEN)
        headers["X-TrackTW-Webhook-Timestamp"] = str(int(time.time()))

    req = urllib.request.Request(HOOKS_URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "body": raw[:500]}
    except urllib.error.HTTPError as exc:
        body_b = exc.read().decode("utf-8", errors="replace")
        return {"ok": False, "status": exc.code, "body": body_b[:500]}
    except Exception as exc:
        return {"ok": False, "status": 0, "body": f"{type(exc).__name__}: {exc}"}


# ── 主流程 ────────────────────────────────────────────────────────────────────
def load_watchlist() -> list[WatchEntry]:
    if not WATCHLIST.exists():
        log.warning("watchlist 檔不存在：%s（建立空範例）", WATCHLIST)
        example = {
            "watch": [
                {
                    "tracking_number": "TEST-POLL-001-NOOP",
                    "carrier_name": "7-Eleven店到店",
                    "label": "測試單（demo）",
                }
            ],
            "_comment": "把想追的單加在 watch 陣列。carrier_name 用 tracktw_carriers 工具查。",
        }
        WATCHLIST.parent.mkdir(parents=True, exist_ok=True)
        WATCHLIST.write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")
        return []
    try:
        data = json.loads(WATCHLIST.read_text(encoding="utf-8"))
        items = data.get("watch") if isinstance(data, dict) else data
        return [WatchEntry(**{k: v for k, v in it.items() if k in WatchEntry.__dataclass_fields__})
                for it in (items or [])]
    except Exception as exc:
        log.error("watchlist 解析失敗：%s", exc)
        return []


def _check_one(entry: WatchEntry, state: dict[str, PackageSnapshot],
               carrier_cache: dict[str, str]) -> tuple[str, PackageSnapshot, Optional[PackageSnapshot], bool]:
    """對單一單跑 import → tracking → 比對。

    回 (key, new_snap, prev_snap, changed)
    """
    key = f"{entry.carrier_name}::{entry.tracking_number}".lower()
    prev = state.get(key)
    try:
        # 決定 carrier_id
        carrier_id = entry.carrier_id or _find_carrier_id(entry.carrier_name, carrier_cache)
        entry.carrier_id = carrier_id  # cache 回 entry

        # 同一單重複 import 是冪等的，OK；不回應就更新
        package_uuid = _import_package(carrier_id, entry.tracking_number)
        data = _track_package(package_uuid)
        latest, count, h = _summarize_events(data)

        snap = PackageSnapshot(
            tracking_number=entry.tracking_number,
            carrier_name=entry.carrier_name,
            carrier_id=carrier_id,
            label=entry.label,
            package_uuid=package_uuid,
            last_state=latest,
            last_event_count=count,
            last_event_hash=h,
            last_checked_at=now_iso(),
            last_changed_at=prev.last_changed_at if prev and prev.last_event_hash == h else now_iso(),
        )
        changed = bool(prev and prev.last_event_hash and prev.last_event_hash != h)
        return (key, snap, prev, changed)
    except Exception as exc:
        log.error("[%s] 處理失敗：%s", key, exc)
        # 失敗時保留前一次快照，僅更新 last_checked_at 與 error
        snap = (prev or PackageSnapshot(
            tracking_number=entry.tracking_number,
            carrier_name=entry.carrier_name,
            carrier_id=entry.carrier_id,
            label=entry.label,
            package_uuid="",
        ))
        snap.last_checked_at = now_iso()
        snap.error = str(exc)[:300]
        return (key, snap, prev, False)


def run_once() -> dict:
    """跑一輪。回 summary。"""
    entries = load_watchlist()
    if not entries:
        log.warning("watchlist 空，無單可追")
        return {"watched": 0, "changed": 0, "errors": 0, "hook_results": []}

    state = load_state()
    log.info("watched=%d  interval=%ds  hooks=%s", len(entries), POLL_INTERVAL, HOOKS_URL)

    # 一次抓 carrier cache，全部 share
    try:
        carrier_cache = _carrier_id_cache()
    except Exception as exc:
        log.error("carrier cache 抓取失敗：%s", exc)
        return {"watched": len(entries), "changed": 0, "errors": len(entries), "hook_results": []}

    changed_count = 0
    error_count = 0
    hook_results: list[dict] = []

    with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
        futures = [pool.submit(_check_one, e, state, carrier_cache) for e in entries]
        for fut in as_completed(futures):
            try:
                key, snap, prev, changed = fut.result()
            except Exception as exc:
                error_count += 1
                log.error("future exception: %s", exc)
                continue
            state[key] = snap
            if snap.error:
                error_count += 1
            if changed:
                changed_count += 1
                log.info("[%s] CHANGED: %s (events=%d, hash=%s)",
                         key, snap.last_state, snap.last_event_count,
                         snap.last_event_hash[:12])
                result = post_to_hook(snap, prev)
                hook_results.append({"key": key, **result})
                log.info("  → hook: ok=%s status=%s body=%s",
                         result.get("ok"), result.get("status"),
                         (result.get("body") or "")[:100])

    save_state(state)
    summary = {
        "watched": len(entries),
        "changed": changed_count,
        "errors": error_count,
        "hook_results": hook_results,
    }
    log.info("done: %s", summary)
    return summary


def cmd_once(_: argparse.Namespace) -> int:
    return 0 if run_once().get("errors", 0) == 0 else 1


def cmd_loop(_: argparse.Namespace) -> int:
    log.info("loop mode, interval=%ds", POLL_INTERVAL)
    while True:
        try:
            run_once()
        except KeyboardInterrupt:
            log.info("interrupted, exiting")
            return 0
        except Exception as exc:
            log.exception("loop iteration crashed: %s", exc)
        log.info("sleep %ds ...", POLL_INTERVAL)
        time.sleep(POLL_INTERVAL)


def cmd_status(_: argparse.Namespace) -> int:
    state = load_state()
    if not state:
        print("(no snapshots yet — run `python tracktw_poller.py once` first)")
        return 0
    print(f"{'key':<60} {'state':<24} {'events':>6}  last_checked")
    print("-" * 110)
    for k, v in state.items():
        err = f" [ERR: {v.error[:30]}]" if v.error else ""
        print(f"{k:<60} {v.last_state[:24]:<24} {v.last_event_count:>6}  {v.last_checked_at}{err}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="TrackTW poller → hooks.edgars.tools")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once", help="跑一輪立即退出").set_defaults(func=cmd_once)
    sub.add_parser("loop", help="持續跑，每輪 sleep interval").set_defaults(func=cmd_loop)
    sub.add_parser("status", help="列出目前快照").set_defaults(func=cmd_status)
    args = p.parse_args()

    # 把 log 也寫到 STATE_DIR/poller.log
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    log.addHandler(fh)

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())