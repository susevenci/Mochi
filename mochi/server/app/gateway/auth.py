"""本机 token 校验（计划书 3.5 / 5.7.4）。

后端只监听 127.0.0.1，并校验一个启动时生成、经 IPC 传给前端的 token，
防止本机其它程序连接。``server_token`` 为空时视为开发模式，不校验。
"""

from __future__ import annotations

import hmac

from starlette.requests import HTTPConnection


def token_matches(supplied: str, expected: str) -> bool:
    return hmac.compare_digest(supplied, expected)


def is_authorized(conn: HTTPConnection, expected: str) -> bool:
    if not expected:
        return True
    supplied = conn.query_params.get("token") or conn.headers.get("x-mochi-token") or ""
    return token_matches(supplied, expected)
