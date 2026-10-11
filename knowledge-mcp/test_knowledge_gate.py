"""Gate #8: a not-accepted retrieval is never presented as Live.

The gateway answers HTTP 200 and signals the gate via qmd.error
("retrieval_not_accepted: ..."), the top-level degraded list, or a runtime meta.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import server as S  # noqa: E402

NOT_ACCEPTED = "retrieval_not_accepted: 檢索尚未驗收"
HIT = {"raw": "qmd://agent-kb/CORE/EXAMPLE.md\nexample body about the gate", "results": []}


def gateway(qmd_error=None, degraded=None, meta=None, qmd=True):
    data = {"honcho": {"status": 200, "hits": []}}
    if qmd:
        data["qmd"] = {"hits": [HIT], "source": "retrieval"}
        if qmd_error:
            data["qmd"]["error"] = qmd_error
    if degraded is not None:
        data["degraded"] = degraded
    if meta is not None:
        data["meta"] = meta
    return data


def fake_http(search_body, health=(200, {"ok": True})):
    def fake(method, path, body=None):
        if path == "/health":
            return health
        return 200, search_body
    return fake


def pack(monkeypatch, body):
    monkeypatch.setattr(S, "http_json", fake_http(body))
    out = S.tool_knowledge_context_pack({"query": "gate example"})
    assert out["isError"] is False
    return out["structuredContent"], out["content"][0]["text"]


# -- knowledge_context_pack -------------------------------------------------

@pytest.mark.parametrize("body", [
    gateway(qmd_error=NOT_ACCEPTED, degraded=["retrieval"]),            # consumer
    gateway(qmd_error=NOT_ACCEPTED),                                    # qmd.error only
    gateway(meta={"status": "Degraded", "degraded": {"retrieval": {
        "reason": "retrieval_not_accepted", "message": "檢索尚未驗收"}}}),  # runtime meta
])
def test_context_pack_is_degraded_when_retrieval_not_accepted(monkeypatch, body):
    sc, text = pack(monkeypatch, body)
    assert sc["status"] == "Degraded"
    assert sc["freshness"]["status"] == "Degraded"
    reasons = {d["backend"]: d["reason"] for d in sc["degraded"]}
    assert reasons["qmd"] == "retrieval_not_accepted"
    qmd = next(d for d in sc["degraded"] if d["backend"] == "qmd")
    assert qmd["message"] == "檢索尚未驗收"
    assert sc["unknown"][0].startswith("retrieval_not_accepted: 檢索尚未驗收")
    assert "never present it as Live" in sc["constraints"][0]
    assert '"status": "Live"' not in text


def test_context_pack_bucket_error_not_accepted(monkeypatch):
    body = gateway()
    body["qmd"]["hits"].append({"error": NOT_ACCEPTED})
    sc, _ = pack(monkeypatch, body)
    assert sc["status"] == "Degraded"
    assert sc["degraded"][0]["reason"] == "retrieval_not_accepted"


@pytest.mark.parametrize("body,reason", [
    (gateway(qmd_error="Connection refused"), "unreachable"),
    (gateway(qmd=False), "unreachable"),                       # missing section: fail-closed
    (gateway(degraded=["retrieval"]), "degraded"),
    (gateway(meta={"status": "Degraded", "degraded": {}}), "degraded"),
])
def test_context_pack_other_degradation_is_never_live(monkeypatch, body, reason):
    sc, _ = pack(monkeypatch, body)
    assert sc["status"] == "Degraded"
    assert any(d["backend"] == "qmd" and d["reason"] == reason for d in sc["degraded"])


def test_context_pack_live_only_when_nothing_degraded(monkeypatch):
    sc, _ = pack(monkeypatch, gateway(meta={"status": "Live", "degraded": {}}))
    assert sc["status"] == "Live" and sc["degraded"] == []


def test_not_accepted_is_not_downgraded_by_a_generic_entry():
    out = S.upstream_degradation(gateway(qmd_error=NOT_ACCEPTED, degraded=["retrieval"]))
    assert out == [{"backend": "qmd", "reason": "retrieval_not_accepted", "message": "檢索尚未驗收"}]


# -- knowledge_status ---------------------------------------------------------

def test_status_reports_retrieval_not_accepted_not_unreachable(monkeypatch):
    monkeypatch.setattr(S, "http_json", fake_http(gateway(qmd_error=NOT_ACCEPTED, degraded=["retrieval"])))
    out = S.tool_knowledge_status({})
    sc = out["structuredContent"]
    assert out["isError"] is True and sc["error"]["code"] == "DEGRADED"
    assert sc["degraded"] == ["qmd"]
    assert sc["degraded_reasons"] == {"qmd": "retrieval_not_accepted"}
    q = sc["backends"]["qmd"]
    assert q["reachable"] is True and q["accepted"] is False
    assert q["reason"] == "retrieval_not_accepted" and q["message"] == "檢索尚未驗收"
    assert "retrieval_not_accepted: 檢索尚未驗收" in sc["error"]["message"]
    assert "unreachable" not in json.dumps(sc["degraded_reasons"])


def test_status_still_reports_unreachable_for_real_outages(monkeypatch):
    monkeypatch.setattr(S, "http_json", fake_http(gateway(qmd_error="Connection refused")))
    sc = S.tool_knowledge_status({})["structuredContent"]
    assert sc["degraded_reasons"] == {"qmd": "unreachable"}
    assert sc["backends"]["qmd"]["reachable"] is False


@pytest.mark.parametrize("honcho,reason", [
    ({"status": 200, "hits": [], "error": "data not migrated"}, "data not migrated"),
    ({"status": 502, "hits": []}, "http_502"),
])
def test_status_reports_the_precise_honcho_reason(monkeypatch, honcho, reason):
    body = gateway()
    body["honcho"] = honcho
    monkeypatch.setattr(S, "http_json", fake_http(body))
    sc = S.tool_knowledge_status({})["structuredContent"]
    assert "honcho" in sc["degraded"]
    assert sc["degraded_reasons"]["honcho"] == reason
    assert reason in sc["error"]["message"]


@pytest.mark.parametrize("err,reason", [
    ("embedding unavailable", "embedding unavailable"),
    ("database cold start", "database cold start"),
    ("data not migrated", "data not migrated"),
])
def test_status_known_qmd_causes_are_never_generic_unreachable(monkeypatch, err, reason):
    monkeypatch.setattr(S, "http_json", fake_http(gateway(qmd_error=err)))
    sc = S.tool_knowledge_status({})["structuredContent"]
    assert sc["degraded_reasons"]["qmd"] == reason


def test_context_pack_carries_data_not_migrated(monkeypatch):
    sc, _ = pack(monkeypatch, gateway(qmd_error="data not migrated"))
    assert sc["status"] == "Degraded"
    assert sc["degraded"][0]["reason"] == "data not migrated"


def test_context_pack_honcho_data_not_migrated_is_degraded(monkeypatch):
    body = gateway()
    body["honcho"] = {"status": 200, "hits": [], "error": "data not migrated"}
    sc, _ = pack(monkeypatch, body)
    assert sc["status"] == "Degraded"
    assert {"backend": "honcho", "reason": "data not migrated", "message": "data not migrated"} in sc["degraded"]
