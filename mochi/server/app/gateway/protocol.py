"""WS 消息契约（计划书第 6 章）。

本文件是**前后端唯一真相源**：由 ``scripts/export_schema.py`` 导出 JSON Schema，
再由 ``scripts/gen-types.mjs`` 生成前端 TS 类型。禁止手改生成物（不变量 I4）。
S0 只定义信封与 ``sys.*`` 消息；``chat.*`` / ``emotion.*`` 在 S1/S3 扩充。
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.utils.ids import ulid

PROTOCOL_VERSION = 1


class MessageType(StrEnum):
    """消息类型，采用 ``域.动作`` 命名（计划书 6.3）。"""

    SYS_HELLO = "sys.hello"
    SYS_HELLO_ACK = "sys.hello_ack"
    SYS_PING = "sys.ping"
    SYS_PONG = "sys.pong"
    SYS_ERROR = "sys.error"
    SYS_STATUS = "sys.status"
    CHAT_USER_INPUT = "chat.user_input"
    CHAT_AGENT_DELTA = "chat.agent_delta"
    CHAT_AGENT_FINAL = "chat.agent_final"
    CHAT_INTERRUPT = "chat.interrupt"
    PERFORMANCE_CUE = "performance.cue"
    INTERACTION_EVENT = "interaction.event"
    EMOTION_UPDATE = "emotion.update"
    PROACTIVE_SPEAK = "proactive.speak"
    AUDIO_IN_BEGIN = "audio.in_begin"
    AUDIO_IN_CHUNK = "audio.in_chunk"
    AUDIO_IN_END = "audio.in_end"
    AUDIO_OUT_BEGIN = "audio.out_begin"
    AUDIO_OUT_CHUNK = "audio.out_chunk"
    AUDIO_OUT_END = "audio.out_end"
    AUDIO_STOP = "audio.stop"
    ASR_PARTIAL = "asr.partial"
    ASR_FINAL = "asr.final"
    ASR_ERROR = "asr.error"
    TOOL_CONFIRM_REQUEST = "tool.confirm_request"
    TOOL_CONFIRM_RESPONSE = "tool.confirm_response"


class Envelope(BaseModel):
    """所有 WS 文本消息的统一信封（计划书 6.2）。

    六个字段在**线格式上全部必填**（``turn_id`` 允许为 null），
    这样导出的 JSON Schema 不会把 ``id`` / ``ts`` 误标为可选。
    发送侧请用 :func:`build_envelope` 构造。
    """

    model_config = ConfigDict(extra="forbid")

    v: int
    type: str
    id: str
    ts: float
    turn_id: str | None = None
    payload: dict[str, Any]


def build_envelope(
    env_type: str,
    payload: dict[str, Any] | None = None,
    *,
    turn_id: str | None = None,
) -> Envelope:
    """构造一条出站信封，自动填充 ``v`` / ``id`` / ``ts``。"""
    return Envelope(
        v=PROTOCOL_VERSION,
        type=env_type,
        id=ulid(),
        ts=time.time(),
        turn_id=turn_id,
        payload=payload or {},
    )


class SysHelloAckPayload(BaseModel):
    """握手响应，含全量状态快照（S0 只含版本与时间）。"""

    server_version: str
    protocol: int = PROTOCOL_VERSION
    server_time: float
    emotion: dict[str, Any] | None = None


class SysPongPayload(BaseModel):
    echo_ts: float | None = None
    server_time: float


class SysErrorPayload(BaseModel):
    code: str
    detail: str | None = None
    retryable: bool = False


class ChatUserInputPayload(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    modality: str = "text"
    session_id: str = "sess_default"


class ChatAgentDeltaPayload(BaseModel):
    delta: str
    index: int = 0
    done: bool = False


class ChatAgentFinalPayload(BaseModel):
    text: str
    route: str
    emotion: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    error: str | None = None
    first_token_ms: int | None = None
    latency_ms: int | None = None


class ChatInterruptPayload(BaseModel):
    reason: str = "user"


class PerformanceCuePayload(BaseModel):
    emotion_label: str
    motion: str
    expression: str | None = None
    priority: str = "normal"
    expression_weight: float = 1.0
    secondary_expression: str | None = None
    secondary_weight: float = 0.0
    auto_release_ms: int | None = None
    tts: dict[str, float] | None = None
    params: dict[str, float] | None = None
    style_hints: list[str] | None = None


class PADPayload(BaseModel):
    valence: float
    arousal: float
    dominance: float


class EmotionCausePayload(BaseModel):
    ts: float
    source: str
    stimulus: str
    delta: PADPayload
    resulting_label: str
    note: str = ""


class EmotionUpdatePayload(BaseModel):
    """``emotion.update``：后端权威情绪快照（不变量 I1）。"""

    pad: PADPayload
    label: str
    secondary_label: str | None = None
    intensity: float
    label_confidence: float = 1.0
    mood: PADPayload
    mood_label: str = "content"
    affinity: float = 0.0
    trust: float = 0.0
    patience: float = 1.0
    idle_seconds: float = 0.0
    causes: list[EmotionCausePayload] = Field(default_factory=list)
    pending_greeting: str | None = None
    label_changed: bool = False
    reason: str = ""
    ts: float = 0.0


class ProactiveSpeakPayload(BaseModel):
    """主动搭话（文案来自角色卡模板）。"""

    text: str
    emotion_label: str
    kind: str = "lonely"


class InteractionEventPayload(BaseModel):
    """前端上报的交互事件（计划书 5.6.6）。

    ``type`` 即刺激标签（pat_head / touch_face / poke_body / teased / dragged），
    S3 的情感引擎把它转成刺激；S2 只做接收与日志。
    """

    type: str = Field(min_length=1, max_length=32)
    area: str = "body"
    count: int = Field(default=1, ge=1)
    x: float = 0.0
    y: float = 0.0


class AudioInBeginPayload(BaseModel):
    sample_rate: int = Field(default=16_000, ge=8_000, le=48_000)
    format: str = "pcm16"
    mode: str = "push_to_talk"


class AudioInChunkPayload(BaseModel):
    data: str  # base64 PCM16
    seq: int = 0


class AudioInEndPayload(BaseModel):
    reason: str = "user"


class AudioOutBeginPayload(BaseModel):
    sample_rate: int = 24_000
    format: str = "mp3"


class AudioOutChunkPayload(BaseModel):
    data: str  # base64 audio
    seq: int = 0
    format: str = "mp3"


class AudioOutEndPayload(BaseModel):
    pass


class AudioStopPayload(BaseModel):
    reason: str = "user"


class AsrPartialPayload(BaseModel):
    text: str
    confidence: float = 0.0


class AsrFinalPayload(BaseModel):
    text: str
    language: str = "zh"
    confidence: float = 0.0
    features: dict[str, float] = Field(default_factory=dict)


class AsrErrorPayload(BaseModel):
    code: str
    detail: str = ""


class ToolConfirmRequestPayload(BaseModel):
    request_id: str
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = 60.0


class ToolConfirmResponsePayload(BaseModel):
    request_id: str
    approved: bool = False
