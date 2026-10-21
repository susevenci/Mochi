"""角色卡 × Live2D 模型交叉校验（T2-13）。

角色卡声明 ``presentation.live2d_model``，模型目录里的 ``*.model3.json`` 声明
动作组 / 表情 / 命中区。两者对不上时，S2 之前只能靠前端 ``hasMotion()`` 兜底；
现在把它变成可查询的报告，前端启动时可以据此提示（而不是静默降级）。

同时承担"衣柜扫描"：``GET /api/v1/live2d/models`` 与绑定报告共用同一份解析。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.character_card import CharacterCard
from app.orchestration.performance import EMOTION_TO_MOTION


def scan_live2d_models(root: Path) -> list[dict[str, Any]]:
    """扫描 ``data/live2d/<目录>/<目录>.model3.json``，返回模型能力清单（衣柜）。"""
    models: list[dict[str, Any]] = []
    if not root.exists():
        return models
    for model_json in sorted(root.glob("*/*.model3.json")):
        try:
            data = json.loads(model_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        refs = data.get("FileReferences") or {}
        motion_map = refs.get("Motions") or {}
        motion_groups = sorted(key for key, value in motion_map.items() if value)
        expressions = refs.get("Expressions") or []
        groups = data.get("Groups") or []
        folder = model_json.parent.name
        models.append(
            {
                "id": folder,
                "name": str(data.get("Name") or folder),
                "url": f"/live2d/{folder}/{model_json.name}",
                "motions": sum(len(group or []) for group in motion_map.values()),
                "expressions": len(expressions),
                "motion_groups": motion_groups,
                "expression_names": [
                    str(item.get("Name")) for item in expressions if item.get("Name")
                ],
                "hit_areas": [
                    str(item.get("Name")) for item in data.get("HitAreas") or [] if item.get("Name")
                ],
                "lipsync_params": next(
                    (
                        list(group.get("Ids") or [])
                        for group in groups
                        if group.get("Name") == "LipSync"
                    ),
                    [],
                ),
            }
        )
    return models


@dataclass(frozen=True)
class BindingReport:
    """角色卡与模型的绑定结论。``ok=False`` 时前端应当降级而不是白屏。"""

    character_id: str
    character_name: str
    declared_model: str | None
    resolved_model: str | None
    model_found: bool
    motion_groups: list[str]
    expression_names: list[str]
    hit_areas: list[str]
    lipsync_params: list[str]
    missing_motions: list[str]
    unknown_expressions: list[str]
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return self.model_found and not self.missing_motions and not self.unknown_expressions

    def to_payload(self) -> dict[str, Any]:
        return {
            "character_id": self.character_id,
            "character_name": self.character_name,
            "declared_model": self.declared_model,
            "resolved_model": self.resolved_model,
            "model_found": self.model_found,
            "motion_groups": self.motion_groups,
            "expression_names": self.expression_names,
            "hit_areas": self.hit_areas,
            "lipsync_params": self.lipsync_params,
            "missing_motions": self.missing_motions,
            "unknown_expressions": self.unknown_expressions,
            "warnings": self.warnings,
            "ok": self.ok,
        }


def validate_binding(card: CharacterCard, models: list[dict[str, Any]]) -> BindingReport:
    """把"角色卡想要的"与"模型实际有的"对一遍，产出可读的差异清单。"""
    declared = card.presentation.live2d_model
    warnings: list[str] = []

    selected: dict[str, Any] | None = None
    if declared:
        selected = next((item for item in models if item["id"] == declared), None)
        if selected is None:
            available = ", ".join(item["id"] for item in models) or "（无）"
            warnings.append(f"角色卡声明的模型 {declared!r} 不存在，可选：{available}")
    else:
        warnings.append("角色卡未声明 presentation.live2d_model")

    if selected is None and models:
        selected = models[0]
        warnings.append(f"回退到衣柜第一个模型：{selected['id']}")

    model_found = selected is not None and (declared is None or selected["id"] == declared)
    motion_groups = list(selected["motion_groups"]) if selected else []
    expression_names = list(selected["expression_names"]) if selected else []
    missing_motions = sorted(set(EMOTION_TO_MOTION.values()) - set(motion_groups))
    unknown_expressions = sorted(
        {name for name in card.presentation.emotion_expressions.values()}
        - set(expression_names)
    )

    if missing_motions and declared:
        model_label = selected["id"] if selected else declared
        warnings.append(f"模型 {model_label} 缺少动作组：{', '.join(missing_motions)}")

    return BindingReport(
        character_id=card.id,
        character_name=card.name,
        declared_model=declared,
        resolved_model=selected["id"] if selected else None,
        model_found=model_found,
        motion_groups=motion_groups,
        expression_names=expression_names,
        hit_areas=list(selected["hit_areas"]) if selected else [],
        lipsync_params=list(selected["lipsync_params"]) if selected else [],
        missing_motions=missing_motions,
        unknown_expressions=unknown_expressions,
        warnings=warnings,
    )
