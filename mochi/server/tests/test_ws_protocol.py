"""WS 协议契约测试（对应 T0-06）。

覆盖：握手、心跳、未知类型、坏 JSON、协议版本不匹配、信封字段校验。
信封在线格式上 id/ts 必填（计划书 6.2），因此测试统一通过 ``_env`` 构造。
"""

from __future__ import annotations

from typing import Any

from app.gateway.protocol import PROTOCOL_VERSION
from fastapi.testclient import TestClient


def _env(env_type: str, payload: dict[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "v": PROTOCOL_VERSION,
        "type": env_type,
        "id": "01J9ZK3M8QWERTYUIOP23456",
        "ts": 1792000000.0,
        "payload": payload or {},
        **extra,
    }


def test_hello_ack(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json(_env("sys.hello"))
        msg = ws.receive_json()
        assert msg["type"] == "sys.hello_ack"
        assert msg["v"] == PROTOCOL_VERSION
        assert msg["payload"]["protocol"] == PROTOCOL_VERSION
        assert isinstance(msg["payload"]["server_version"], str)
        # 服务端生成新的 id/ts（不是回显客户端的那份）
        assert len(msg["id"]) == 26
        assert msg["ts"] > 0


def test_ping_pong_echoes_ts(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json(_env("sys.ping", {"ts": 123.5}))
        msg = ws.receive_json()
        assert msg["type"] == "sys.pong"
        assert msg["payload"]["echo_ts"] == 123.5
        assert msg["payload"]["server_time"] > 0


def test_unknown_type_returns_error(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json(_env("chat.magic"))
        msg = ws.receive_json()
        assert msg["type"] == "sys.error"
        assert msg["payload"]["code"] == "UNKNOWN_TYPE"
        assert msg["payload"]["detail"] == "chat.magic"


def test_bad_json_returns_error(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_text("{not-json")
        msg = ws.receive_json()
        assert msg["type"] == "sys.error"
        assert msg["payload"]["code"] == "BAD_JSON"


def test_protocol_mismatch(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json(_env("sys.hello", v=PROTOCOL_VERSION + 1))
        msg = ws.receive_json()
        assert msg["type"] == "sys.error"
        assert msg["payload"]["code"] == "PROTOCOL_MISMATCH"


def test_missing_type_is_bad_envelope(client: TestClient) -> None:
    with client.websocket_connect("/ws") as ws:
        payload = _env("sys.hello")
        payload.pop("type")
        ws.send_json(payload)
        msg = ws.receive_json()
        assert msg["type"] == "sys.error"
        assert msg["payload"]["code"] == "BAD_ENVELOPE"


def test_missing_id_is_bad_envelope(client: TestClient) -> None:
    """信封字段在线格式必填：缺 id 必须被拒（防止前端类型失真）。"""
    with client.websocket_connect("/ws") as ws:
        payload = _env("sys.hello")
        payload.pop("id")
        ws.send_json(payload)
        msg = ws.receive_json()
        assert msg["type"] == "sys.error"
        assert msg["payload"]["code"] == "BAD_ENVELOPE"
