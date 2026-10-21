from __future__ import annotations

from fastapi.testclient import TestClient

from app.gateway.protocol import PROTOCOL_VERSION


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["protocol"] == PROTOCOL_VERSION
    assert body["connections"] == 0
    assert body["uptime_s"] >= 0


def test_sys_info(client: TestClient) -> None:
    resp = client.get("/api/v1/sys/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["protocol"] == PROTOCOL_VERSION
    assert body["token_required"] is False
    assert body["llm_configured"] is False
