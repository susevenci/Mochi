"""导出协议 JSON Schema（T0-04）。

运行：``python scripts/export_schema.py``
产出：``shared/schema/protocol.schema.json``（契约单一真相源，见不变量 I4）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "shared" / "schema" / "protocol.schema.json"


def _load_protocol() -> Any:
    """延迟导入：先把 server/ 放进 sys.path，再取协议模块。"""
    sys.path.insert(0, str(ROOT / "server"))
    from app.gateway import protocol

    return protocol


def build_bundle() -> dict[str, object]:
    protocol = _load_protocol()
    models = {
        "Envelope": protocol.Envelope,
        "SysHelloAckPayload": protocol.SysHelloAckPayload,
        "SysPongPayload": protocol.SysPongPayload,
        "SysErrorPayload": protocol.SysErrorPayload,
        "ChatUserInputPayload": protocol.ChatUserInputPayload,
        "ChatAgentDeltaPayload": protocol.ChatAgentDeltaPayload,
        "ChatAgentFinalPayload": protocol.ChatAgentFinalPayload,
        "ChatInterruptPayload": protocol.ChatInterruptPayload,
        "PerformanceCuePayload": protocol.PerformanceCuePayload,
        "InteractionEventPayload": protocol.InteractionEventPayload,
        "PADPayload": protocol.PADPayload,
        "EmotionCausePayload": protocol.EmotionCausePayload,
        "EmotionUpdatePayload": protocol.EmotionUpdatePayload,
        "ProactiveSpeakPayload": protocol.ProactiveSpeakPayload,
        "AudioInBeginPayload": protocol.AudioInBeginPayload,
        "AudioInChunkPayload": protocol.AudioInChunkPayload,
        "AudioInEndPayload": protocol.AudioInEndPayload,
        "AudioOutBeginPayload": protocol.AudioOutBeginPayload,
        "AudioOutChunkPayload": protocol.AudioOutChunkPayload,
        "AudioOutEndPayload": protocol.AudioOutEndPayload,
        "AudioStopPayload": protocol.AudioStopPayload,
        "AsrPartialPayload": protocol.AsrPartialPayload,
        "AsrFinalPayload": protocol.AsrFinalPayload,
        "AsrErrorPayload": protocol.AsrErrorPayload,
        "ToolConfirmRequestPayload": protocol.ToolConfirmRequestPayload,
        "ToolConfirmResponsePayload": protocol.ToolConfirmResponsePayload,
    }
    defs: dict[str, object] = {}
    for name, model in models.items():
        schema = model.model_json_schema(ref_template="#/$defs/{model}")
        defs[name] = schema
    defs["MessageType"] = {
        "type": "string",
        "enum": [member.value for member in protocol.MessageType],
        "title": "MessageType",
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://mochi.local/schema/protocol.schema.json",
        "title": "Mochi WS Protocol",
        "protocolVersion": protocol.PROTOCOL_VERSION,
        "$defs": defs,
    }


def main() -> int:
    bundle = build_bundle()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    defs = bundle["$defs"]
    count = len(defs) if isinstance(defs, dict) else 0
    print(f"wrote {OUT_PATH} ({count} defs)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
