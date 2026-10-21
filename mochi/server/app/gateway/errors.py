"""统一错误码与错误信封（计划书 6.7）。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from .protocol import MessageType, SysErrorPayload, build_envelope


class ErrorCode(StrEnum):
    BAD_JSON = "BAD_JSON"
    BAD_ENVELOPE = "BAD_ENVELOPE"
    PROTOCOL_MISMATCH = "PROTOCOL_MISMATCH"
    UNKNOWN_TYPE = "UNKNOWN_TYPE"
    AUTH_FAILED = "AUTH_FAILED"
    LLM_AUTH_FAILED = "LLM_AUTH_FAILED"
    INTERNAL = "INTERNAL"


def error_envelope(
    code: ErrorCode,
    *,
    detail: str | None = None,
    retryable: bool = False,
    turn_id: str | None = None,
) -> dict[str, Any]:
    payload = SysErrorPayload(code=code.value, detail=detail, retryable=retryable)
    env = build_envelope(MessageType.SYS_ERROR, payload.model_dump(), turn_id=turn_id)
    return env.model_dump(mode="json")
