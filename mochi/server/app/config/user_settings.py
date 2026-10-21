"""用户可改的运行时设置（``settings.json``），与 ``.env`` 分离（计划书 4.8）。

``.env`` 放机密与环境；``settings.json`` 放窗口位置、置顶、穿透、自启等 UI 状态。
写入采用「临时文件 + 原子替换」，避免进程被杀时留下半个文件（3.5.4）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WINDOW_DEFAULTS: dict[str, Any] = {
    # position: {"x": int, "y": int, "display": str}
    # 计划书 9.2.3：存"显示器标识 + 相对坐标"，恢复时校验显示器是否仍存在
    "position": None,
    "always_on_top": True,
    "click_through": False,
    "autostart": False,
}


class UserSettings:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        self.load()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, Any]:
        """缺失或损坏时回落到默认值，绝不抛异常（程序必须能起来）。"""
        defaults = {**self._defaults()}
        if not self._path.exists():
            self._data = defaults
            return self.get_all()
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._data = defaults
            return self.get_all()

        data = raw if isinstance(raw, dict) else {}
        window = {**WINDOW_DEFAULTS, **(data.get("window") or {})}
        self._data = {**data, "window": window}
        return self.get_all()

    def get_all(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._data))

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def patch(self, updates: dict[str, Any]) -> dict[str, Any]:
        """浅合并写入并落盘；``window`` 为深一层的合并。"""
        for key, value in updates.items():
            if key == "window" and isinstance(value, dict):
                window = dict(self._data.get("window", WINDOW_DEFAULTS))
                window.update(value)
                self._data["window"] = window
            else:
                self._data[key] = value
        self.save()
        return self.get_all()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        payload = json.dumps(self._data, ensure_ascii=False, indent=2) + "\n"
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self._path)

    @staticmethod
    def _defaults() -> dict[str, Any]:
        return {"window": dict(WINDOW_DEFAULTS)}
