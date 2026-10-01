"""knowledge_status must not count QMD error buckets as hits (2026-09-26..10-02 false green)."""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import server as S


def test_bucket_error_is_unreachable():
    q = S._backend_health_qmd({"hits": [{"error": "[Errno 111] Connection refused"}]}, 200)
    assert q["reachable"] is False and q["hit_count"] == 0 and "refused" in q["error"]


def test_top_level_qmd_error_is_unreachable():
    assert S._backend_health_qmd({"error": "Connection refused", "hits": []}, 200)["reachable"] is False


def test_missing_qmd_section_is_unreachable():
    assert S._backend_health_qmd(None, 200)["reachable"] is False


def test_healthy_qmd():
    q = S._backend_health_qmd({"hits": [{"raw": "x", "results": []}], "source": "retrieval/qmd"}, 200)
    assert q["reachable"] is True and q["hit_count"] == 1 and q["error"] is None


def test_honcho_non_200_is_unreachable():
    assert S._backend_health_honcho({"status": 502, "hits": []}, 200)["reachable"] is False


def test_status_reports_degraded_on_qmd_bucket_error(monkeypatch):
    def fake(method, path, body=None):
        if path == "/health":
            return 200, {"ok": True}
        return 200, {"honcho": {"status": 200, "hits": [{}]}, "qmd": {"hits": [{"error": "Connection refused"}]}}
    monkeypatch.setattr(S, "http_json", fake)
    out = S.tool_knowledge_status({})
    text = out["content"][0]["text"]
    assert "DEGRADED" in text and '"qmd"' in text
