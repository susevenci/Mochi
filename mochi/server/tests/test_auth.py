"""Token 鉴权测试（计划书 3.5：后端只绑 127.0.0.1 且校验 token）。"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config.settings import Settings
from app.gateway.protocol import PROTOCOL_VERSION
from app.main import create_app


@pytest.fixture()
def secured_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path, server_token="s3cret")))


def test_ws_rejects_missing_token(secured_client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect), secured_client.websocket_connect("/ws"):
        pass


def test_ws_accepts_valid_token(secured_client: TestClient) -> None:
    hello = {
        "v": PROTOCOL_VERSION,
        "type": "sys.hello",
        "id": "01J9ZK3M8QWERTYUIOP23456",
        "ts": 1792000000.0,
        "payload": {},
    }
    with secured_client.websocket_connect("/ws?token=s3cret") as ws:
        ws.send_json(hello)
        assert ws.receive_json()["type"] == "sys.hello_ack"


def test_rest_requires_token(secured_client: TestClient) -> None:
    assert secured_client.get("/api/v1/sys/info").status_code == 401
    ok = secured_client.get("/api/v1/sys/info", headers={"X-Mochi-Token": "s3cret"})
    assert ok.status_code == 200
    assert ok.json()["token_required"] is True
