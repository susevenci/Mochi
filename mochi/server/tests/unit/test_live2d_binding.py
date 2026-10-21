"""角色卡 × 模型交叉校验（T2-13）单元测试。

坐标：``orchestration/live2d_binding.py`` 同时承担衣柜扫描与绑定校验，
所以这里既测"能不能读出模型能力"，也测"对不上时的告警与回退"。
"""

from __future__ import annotations

import json
from pathlib import Path

from app.config.character_card import CharacterCard, Presentation
from app.orchestration.live2d_binding import scan_live2d_models, validate_binding
from app.orchestration.performance import EMOTION_TO_MOTION

# 表现映射表是"情绪 → 动作组"的唯一真相源：模型要"齐全"就得覆盖它的所有取值
ALL_MOTIONS = sorted(set(EMOTION_TO_MOTION.values()))


def _card(model: str | None, expressions: dict[str, str] | None = None) -> CharacterCard:
    return CharacterCard(
        id="tsundere",
        name="星璃",
        identity={"full_name": "星璃", "role": "猫耳少女", "personality": "傲娇"},
        presentation=Presentation(
            live2d_model=model,
            emotion_expressions=expressions or {},
        ),
    )


def _write_model(
    root: Path,
    folder: str,
    *,
    motions: list[str],
    expressions: list[str] | None = None,
    lipsync_ids: list[str] | None = None,
    hit_areas: list[str] | None = None,
) -> None:
    model_dir = root / folder
    model_dir.mkdir(parents=True)
    payload = {
        "Version": 3,
        "Name": folder,
        "FileReferences": {
            "Moc": f"{folder}.moc3",
            "Motions": {name: [{"File": f"motions/{name}.motion3.json"}] for name in motions},
            "Expressions": [
                {"Name": name, "File": f"{index}.exp3.json"}
                for index, name in enumerate(expressions or [])
            ],
        },
        "Groups": (
            [{"Target": "Parameter", "Name": "LipSync", "Ids": lipsync_ids}]
            if lipsync_ids
            else []
        ),
        "HitAreas": [{"Id": f"Part{i}", "Name": name} for i, name in enumerate(hit_areas or [])],
    }
    (model_dir / f"{folder}.model3.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def test_scan_reports_capabilities(tmp_path: Path) -> None:
    _write_model(
        tmp_path,
        "qiye_10",
        motions=sorted(ALL_MOTIONS),
        expressions=["shy"],
        lipsync_ids=["ParamMouthOpenY_SD"],
        hit_areas=["HitAreaHead"],
    )
    models = scan_live2d_models(tmp_path)
    assert len(models) == 1
    model = models[0]
    assert model["id"] == "qiye_10"
    assert model["url"] == "/live2d/qiye_10/qiye_10.model3.json"
    assert model["motions"] == len(ALL_MOTIONS)
    assert model["motion_groups"] == sorted(ALL_MOTIONS)
    assert model["expression_names"] == ["shy"]
    assert model["lipsync_params"] == ["ParamMouthOpenY_SD"]
    assert model["hit_areas"] == ["HitAreaHead"]


def test_binding_ok_when_card_and_model_match(tmp_path: Path) -> None:
    _write_model(tmp_path, "qiye_10", motions=sorted(ALL_MOTIONS), expressions=["shy"])
    report = validate_binding(_card("qiye_10", {"shy": "shy"}), scan_live2d_models(tmp_path))
    assert report.ok is True
    assert report.model_found is True
    assert report.missing_motions == []
    assert report.unknown_expressions == []


def test_binding_falls_back_when_declared_model_missing(tmp_path: Path) -> None:
    _write_model(tmp_path, "devil", motions=sorted(ALL_MOTIONS))
    report = validate_binding(_card("ghost_model"), scan_live2d_models(tmp_path))
    assert report.model_found is False
    assert report.resolved_model == "devil"
    assert any("不存在" in warning for warning in report.warnings)


def test_binding_reports_missing_motions(tmp_path: Path) -> None:
    """devil 这类没有动作组的模型：必须把缺的动作列出来，让前端走表情兜底。"""
    _write_model(tmp_path, "devil", motions=[])
    report = validate_binding(_card("devil"), scan_live2d_models(tmp_path))
    assert report.model_found is True
    assert report.ok is False
    assert set(report.missing_motions) == set(ALL_MOTIONS)


def test_binding_reports_unknown_expressions(tmp_path: Path) -> None:
    _write_model(tmp_path, "devil", motions=sorted(ALL_MOTIONS), expressions=["exp1"])
    report = validate_binding(_card("devil", {"shy": "exp9"}), scan_live2d_models(tmp_path))
    assert report.unknown_expressions == ["exp9"]
    assert report.ok is False


def test_binding_without_declaration_uses_first_model(tmp_path: Path) -> None:
    _write_model(tmp_path, "a_model", motions=sorted(ALL_MOTIONS))
    _write_model(tmp_path, "b_model", motions=sorted(ALL_MOTIONS))
    report = validate_binding(_card(None), scan_live2d_models(tmp_path))
    assert report.resolved_model == "a_model"
    assert any("未声明" in warning for warning in report.warnings)
