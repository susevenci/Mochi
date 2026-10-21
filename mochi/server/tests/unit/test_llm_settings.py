"""LLM 运行时配置测试：优先级、掩码、热更新、路由校验。"""

from __future__ import annotations

import json
from pathlib import Path

from app.config.llm_settings import LLMSettingsService, mask_key, parse_models
from app.config.settings import Settings
from app.config.user_settings import UserSettings
from fastapi.testclient import TestClient


def _env_settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        llm_base_url="https://api.example.com/v1",
        llm_api_key="env-key-123456",
        llm_model_chat="env-model",
    )


def test_mask_key() -> None:
    assert mask_key("") == ""
    assert mask_key("short") == "••••"
    assert mask_key("sk-1234567890abcdef") == "sk••••cdef"


def test_env_is_default_source(tmp_path: Path) -> None:
    service = LLMSettingsService(_env_settings(tmp_path), UserSettings(tmp_path / "settings.json"))
    config = service.config
    assert config.base_url == "https://api.example.com/v1"
    assert config.model == "env-model"
    assert config.source == "env"
    # 桌宠默认关闭思考
    assert config.disable_thinking is True


def test_disable_thinking_toggle(tmp_path: Path) -> None:
    import asyncio

    service = LLMSettingsService(_env_settings(tmp_path), UserSettings(tmp_path / "settings.json"))
    asyncio.run(service.update(disable_thinking=False))
    assert service.config.disable_thinking is False
    asyncio.run(service.update(disable_thinking=True))
    assert service.config.disable_thinking is True


def test_user_settings_override_env(tmp_path: Path) -> None:
    user = UserSettings(tmp_path / "settings.json")
    user.patch({"llm": {"base_url": "http://127.0.0.1:8080/v1", "model": "local-model"}})
    service = LLMSettingsService(_env_settings(tmp_path), user)
    config = service.config
    assert config.base_url == "http://127.0.0.1:8080/v1"
    assert config.model == "local-model"
    assert config.api_key == "env-key-123456"  # 未覆盖则回落 .env
    assert config.source == "user"


def test_update_persists_and_switches_model(tmp_path: Path) -> None:
    import asyncio

    path = tmp_path / "settings.json"
    service = LLMSettingsService(_env_settings(tmp_path), UserSettings(path))
    config = asyncio.run(
        service.update(base_url="http://127.0.0.1:9999/v1", api_key="local", model="qwen")
    )
    assert config.model == "qwen"
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["llm"]["base_url"] == "http://127.0.0.1:9999/v1"
    assert on_disk["llm"]["model"] == "qwen"


def test_parse_models() -> None:
    payload = {"data": [{"id": "b"}, {"id": "a"}, {"id": "a"}, {"x": 1}, "junk"]}
    assert parse_models(payload) == ["a", "b"]
    assert parse_models({}) == []
    assert parse_models(None) == []


# ── 路由 ──


def test_get_llm_config_masks_key(client: TestClient, settings: Settings) -> None:
    settings.llm_api_key = "sk-abcdefghijklmnop"
    # 重建服务以反映测试设置
    client.app.state.ctx.llm = LLMSettingsService(settings, client.app.state.ctx.user_settings)  # type: ignore[attr-defined]
    body = client.get("/api/v1/config/llm").json()
    assert body["api_key_set"] is True
    assert body["api_key_hint"] == "sk••••mnop"
    assert "sk-abcdefghijklmnop" not in json.dumps(body)


def test_patch_llm_rejects_bad_base_url(client: TestClient) -> None:
    resp = client.patch("/api/v1/config/llm", json={"base_url": "not-a-url"})
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


def test_patch_llm_rejects_empty_key(client: TestClient) -> None:
    resp = client.patch("/api/v1/config/llm", json={"api_key": "  "})
    assert resp.status_code == 400


def test_patch_llm_ok_and_hot_swap(client: TestClient, settings: Settings) -> None:
    resp = client.patch(
        "/api/v1/config/llm",
        json={"base_url": "http://127.0.0.1:8080/v1/", "api_key": "local", "model": "qwen"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["base_url"] == "http://127.0.0.1:8080/v1"  # 去掉尾斜杠
    assert body["model"] == "qwen"
    assert body["source"] == "user"
    # 立即生效：同一个 service 实例的配置已更新
    assert client.app.state.ctx.llm.config.model == "qwen"  # type: ignore[attr-defined]


def test_list_models_route(client: TestClient) -> None:
    async def fake_models() -> list[str]:
        return ["m1", "m2"]

    client.app.state.ctx.llm.list_models = fake_models  # type: ignore[attr-defined,method-assign]
    body = client.get("/api/v1/llm/models").json()
    assert body["models"] == ["m1", "m2"]
    assert body["count"] == 2
