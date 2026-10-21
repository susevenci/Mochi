"""对话链路冒烟（T1-09 / T1-12 验收）：真实 WS + 真实 LLM。

运行：
    python scripts/smoke_chat.py --text 你好呀
    python scripts/smoke_chat.py --turn 我叫阿哲 --turn 我叫什么名字？
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid

import websockets

HELLO_ID = "01SMOKEHELLO00000000000000"

# 预置场景：避免在 shell 里传含空格的参数
SCENARIOS: dict[str, list[str]] = {
    "hello": ["你好呀"],
    "memory": ["我叫阿哲", "我叫什么名字"],
    "role": ["/role set genki", "你好呀"],
    "help": ["/help"],
}


async def _one_turn(ws: websockets.WebSocketClientProtocol, text: str, timeout: float) -> dict:
    turn_id = "SMOKE" + uuid.uuid4().hex[:12].upper()
    envelope = {
        "v": 1,
        "type": "chat.user_input",
        "id": "01SMOKECHAT" + uuid.uuid4().hex[:14].upper(),
        "ts": time.time(),
        "turn_id": turn_id,
        "payload": {"text": text},
    }
    started = time.perf_counter()
    await ws.send(json.dumps(envelope))

    parts: list[str] = []
    final: dict = {}
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        message = json.loads(raw)
        if message.get("turn_id") != turn_id:
            continue
        if message["type"] == "chat.agent_delta":
            parts.append(message["payload"]["delta"])
        elif message["type"] == "chat.agent_final":
            final = message["payload"]
            break
        elif message["type"] == "sys.error":
            raise RuntimeError(f"server error: {message['payload']}")
    return {
        "input": text,
        "streamed": "".join(parts),
        "final": final,
        "wall_ms": (time.perf_counter() - started) * 1000,
    }


async def main(url: str, texts: list[str], timeout: float) -> int:
    async with websockets.connect(url) as ws:
        hello = {"v": 1, "type": "sys.hello", "id": HELLO_ID, "ts": time.time(), "payload": {}}
        await ws.send(json.dumps(hello))
        ack = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print("hello:", ack["type"], "server=", ack["payload"].get("server_version"))

        failed = False
        for text in texts:
            result = await _one_turn(ws, text, timeout)
            final = result["final"]
            print("─" * 60)
            print("user:", text)
            print("assistant:", repr(result["streamed"] or final.get("text", "")))
            print(
                f"route={final.get('route')} emotion={final.get('emotion')} "
                f"first_token_ms={final.get('first_token_ms')} latency_ms={final.get('latency_ms')}"
            )
            if not final.get("text"):
                print("FAIL: final 为空")
                failed = True
            if final.get("error"):
                print("error:", final["error"])
                failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://127.0.0.1:8765/ws")
    parser.add_argument("--text", default="")
    parser.add_argument("--turn", action="append", default=None)
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    turns = args.turn or SCENARIOS.get(args.scenario) or ([args.text] if args.text else ["你好呀"])
    raise SystemExit(asyncio.run(main(args.url, turns, args.timeout)))
