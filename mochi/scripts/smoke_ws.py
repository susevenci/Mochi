"""WS 冒烟测试（S0 验收用）：真实连接后端，验证 hello/ack 与 ping/pong。

运行：``python scripts/smoke_ws.py [ws://127.0.0.1:8765/ws]``
"""

from __future__ import annotations

import asyncio
import json
import sys

import websockets

HELLO_ID = "01J9ZK3M8QWERTYUIOP23456"
PING_ID = "01J9ZK3M8QWERTYUIOP23457"


async def main(url: str) -> int:
    async with websockets.connect(url) as ws:
        hello = {"v": 1, "type": "sys.hello", "id": HELLO_ID, "ts": 1.0, "payload": {}}
        await ws.send(json.dumps(hello))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print("hello_ack:", json.dumps(ack, ensure_ascii=False))
        if ack.get("type") != "sys.hello_ack":
            print("FAIL: 期望 sys.hello_ack")
            return 1

        ping = {
            "v": 1,
            "type": "sys.ping",
            "id": PING_ID,
            "ts": 2.0,
            "payload": {"ts": 123.5},
        }
        await ws.send(json.dumps(ping))
        pong = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        print("pong:", json.dumps(pong, ensure_ascii=False))
        if pong.get("payload", {}).get("echo_ts") != 123.5:
            print("FAIL: pong 未回显 ts")
            return 1

    print("smoke ok")
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8765/ws"
    raise SystemExit(asyncio.run(main(target)))
