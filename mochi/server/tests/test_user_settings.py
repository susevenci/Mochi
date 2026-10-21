"""settings.json 读写测试（T0-03）：默认值、原子写、损坏回落、REST 通路。"""

from __future__ import annotations

import json
from pathlib import Path

from app.config.settings import Settings
from app.config.user_settings import UserSettings
from fastapi.testclient import TestClient


def test_defaults_when_missing(tmp_path: Path) -> None:
    store = UserSettings(tmp_path / "settings.json")
    data = store.get_all()
    assert data["window"]["always_on_top"] is True
    assert data["window"]["position"] is None
    assert not (tmp_path / "settings.json").exists()  # 只读不落盘


def test_patch_persists_and_merges(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = UserSettings(path)
    store.patch({"window": {"position": {"x": 10, "y": 20, "display": "DISPLAY1"}}})

    assert path.exists()
    reloaded = UserSettings(path)
    assert reloaded.get_all()["window"]["position"] == {"x": 10, "y": 20, "display": "DISPLAY1"}
    # 深一层合并：未指定的字段保留默认
    assert reloaded.get_all()["window"]["always_on_top"] is True


def test_corrupted_file_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{oops", encoding="utf-8")
    store = UserSettings(path)
    assert store.get_all()["window"]["autostart"] is False


def test_rest_get_and_patch(client: TestClient, settings: Settings) -> None:
    resp = client.get("/api/v1/config/user")
    assert resp.status_code == 200
    assert resp.json()["window"]["click_through"] is False

    patched = client.patch("/api/v1/config/user", json={"window": {"click_through": True}})
    assert patched.status_code == 200
    assert patched.json()["window"]["click_through"] is True

    again = client.get("/api/v1/config/user")
    assert again.json()["window"]["click_through"] is True

    # 落盘验证
    on_disk = json.loads((settings.data_dir / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["window"]["click_through"] is True


def test_rest_rejects_unknown_keys(client: TestClient) -> None:
    resp = client.patch("/api/v1/config/user", json={"llm_api_key": "leak"})
    assert resp.status_code == 400
