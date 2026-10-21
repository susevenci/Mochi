"""LLM 连通性与流式探测（T1-01 验证工具）。

用法：
    set LLM_API_KEY=... && python scripts/probe_llm.py --model deepseek-ai/deepseek-v4.1-flash

验证三件事：非流式可用、流式可用、首 token 延迟。
"""

from __future__ import annotations

import argparse
import json
import os
import time

import httpx


def _check(ok: bool, label: str, detail: str) -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}  {detail}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", ""))
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL_CHAT", ""))
    parser.add_argument("--prompt", default="用一句话介绍你自己")
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--api-key", default="", help="优先于 LLM_API_KEY 环境变量")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--no-think", action="store_true", help="请求体中关闭 Qwen 思考模式")
    parser.add_argument("--mode", choices=["chat", "completions"], default="chat")
    args = parser.parse_args()
    prompt = args.prompt
    body_extra: dict[str, object] = {}
    if args.no_think:
        # LM Studio / llama.cpp 透传给 chat template；Qwen3 系列识 enable_thinking
        body_extra["chat_template_kwargs"] = {"enable_thinking": False}

    key = args.api_key or os.environ.get("LLM_API_KEY", "")
    if not key:
        print("缺少 LLM_API_KEY 环境变量")
        return 2
    base = (args.base_url or "https://integrate.api.nvidia.com/v1").rstrip("/")
    model = args.model or "deepseek-ai/deepseek-v4.1-flash"
    headers = {"Authorization": f"Bearer {key}"}
    # trust_env=False：绕过系统代理环境变量，避免代理对 POST 的干扰
    client = httpx.Client(trust_env=False, timeout=args.timeout)
    print(f"base={base} model={model}")

    if args.mode == "completions":
        resp = client.post(
            f"{base}/completions",
            headers=headers,
            json={"model": model, "prompt": prompt, "max_tokens": args.max_tokens},
        )
        print(f"status={resp.status_code} raw={resp.text[:600]}")
        return 0 if resp.status_code == 200 else 1

    # ── 非流式 ──
    started = time.perf_counter()
    try:
        resp = client.post(
            f"{base}/chat/completions",
            headers=headers,
            timeout=args.timeout,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": args.max_tokens,
                "temperature": 0.7,
                **body_extra,
            },
        )
    except httpx.HTTPError as exc:
        print(f"[FAIL] 非流式请求异常: {exc}")
        return 1
    elapsed = time.perf_counter() - started
    if resp.status_code != 200:
        _check(False, "非流式", f"HTTP {resp.status_code} {resp.text[:300]}")
        return 1
    print(f"        raw={resp.text[:600]}")
    data = resp.json()
    choices = data.get("choices") or []
    if not choices:
        print("[FAIL] 非流式返回空 choices")
        return 1
    message = choices[0].get("message") or {}
    content = message.get("content") or message.get("reasoning_content") or ""
    _check(bool(content), "非流式", f"{elapsed:.2f}s · {content[:60]!r}")
    print(f"        message_keys={sorted(message.keys())} usage={data.get('usage')}")

    # ── 流式 ──
    started = time.perf_counter()
    first_token: float | None = None
    chunks = 0
    reasoning_chunks = 0
    parts: list[str] = []
    try:
        with client.stream(
            "POST",
            f"{base}/chat/completions",
            headers=headers,
            timeout=args.timeout,
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": args.max_tokens,
                "stream": True,
                **body_extra,
            },
        ) as stream:
            if stream.status_code != 200:
                error_body = stream.read()[:300].decode("utf-8", "ignore")
                print(f"[FAIL] 流式 HTTP {stream.status_code} {error_body}")
                return 1
            for line in stream.iter_lines():
                if not line.startswith("data: "):
                    continue
                raw = line[6:].strip()
                if raw == "[DONE]":
                    break
                obj = json.loads(raw)
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta_obj = choices[0].get("delta") or {}
                if delta_obj.get("reasoning_content"):
                    reasoning_chunks += 1
                delta = delta_obj.get("content")
                if delta:
                    if first_token is None:
                        first_token = time.perf_counter() - started
                    chunks += 1
                    parts.append(delta)
    except httpx.HTTPError as exc:
        print(f"[FAIL] 流式请求异常: {exc}")
        return 1

    ok = _check(
        first_token is not None,
        "流式",
        (
            f"首 token {first_token or 0:.2f}s · "
            f"content {chunks} chunks · reasoning {reasoning_chunks} chunks"
        ),
    )
    print(f"        文本: {''.join(parts)[:80]!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
