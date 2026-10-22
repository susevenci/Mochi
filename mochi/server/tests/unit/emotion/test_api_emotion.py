"""情感调试 API（T3-01/18）：状态、注入、时间旅行、人格写回与导出。"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_emotion_state_and_catalog(client: TestClient) -> None:
    state = client.get("/api/v1/emotion/state")
    assert state.status_code == 200
    body = state.json()
    assert body["state"]["label"] == "neutral"
    assert body["character"] == "tsundere"

    catalog = client.get("/api/v1/emotion/catalog")
    assert catalog.status_code == 200
    data = catalog.json()
    assert len(data["labels"]) == 16
    assert any(item["tag"] == "user_praise" for item in data["stimuli"])
    assert data["persona"]["reactivity"]["insult"] == 1.25


def test_inject_stimulus_updates_state_and_history(client: TestClient) -> None:
    before = client.get("/api/v1/emotion/state").json()["state"]["pad"]["valence"]
    response = client.post(
        "/api/v1/emotion/stimulus",
        json={"tag": "user_praise", "magnitude": 1.0},
    )
    assert response.status_code == 200
    assert response.json()["pad"]["valence"] > before

    history = client.get("/api/v1/emotion/history?limit=10")
    assert history.status_code == 200
    assert history.json()["count"] >= 1


def test_inject_unknown_stimulus_returns_400(client: TestClient) -> None:
    response = client.post(
        "/api/v1/emotion/stimulus",
        json={"tag": "not_a_stimulus"},
    )
    assert response.status_code == 400


def test_advance_and_greeting(client: TestClient) -> None:
    response = client.post("/api/v1/emotion/advance", json={"seconds": 8 * 3600})
    assert response.status_code == 200
    state = response.json()
    assert state["pending_greeting"] == "long_absence"
    # 重逢会把 idle 归零（用户回来了），这是预期行为
    assert state["idle_seconds"] == 0.0

    greeting = client.post("/api/v1/emotion/greeting/consume")
    assert greeting.status_code == 200
    body = greeting.json()
    assert body["greeting"] == "long_absence"
    assert body["text"]
    # 第二次已被消费
    assert client.post("/api/v1/emotion/greeting/consume").json()["greeting"] is None


def test_patch_persona(client: TestClient) -> None:
    response = client.patch(
        "/api/v1/emotion/persona",
        json={"reactivity": {"praise": 1.7}, "refractory_seconds": 3.0},
    )
    assert response.status_code == 200
    persona = response.json()["persona"]
    assert persona["reactivity"]["praise"] == 1.7
    assert persona["refractory_seconds"] == 3.0

    catalog = client.get("/api/v1/emotion/catalog").json()
    assert catalog["persona"]["reactivity"]["praise"] == 1.7


def test_export_trace(client: TestClient) -> None:
    client.post("/api/v1/emotion/stimulus", json={"tag": "user_care"})
    response = client.get("/api/v1/emotion/export?limit=5")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    body = response.json()
    assert body["version"] == 1
    assert body["state"]["label"]
    assert isinstance(body["history"], list)
