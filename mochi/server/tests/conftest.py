from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from app.config.settings import Settings
from app.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """临时数据目录 + 关闭 token，避免污染 %APPDATA% 与依赖本机环境。"""
    return Settings(data_dir=tmp_path, server_token="", llm_api_key="")


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client
