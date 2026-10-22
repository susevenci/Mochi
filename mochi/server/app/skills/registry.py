"""Skills 懒加载（T6-12）：目录扫描、30 分钟自动卸载、路径安全。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

ACTIVE_TTL_SECONDS = 1800
MAX_BODY_CHARS = 12000
PAGE_CHARS = 2000


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    path: Path


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._skills: dict[str, SkillMeta] = {}
        self._active: dict[str, float] = {}
        self.reload()

    @property
    def root(self) -> Path:
        return self._root

    def reload(self) -> None:
        self._skills.clear()
        if not self._root.is_dir():
            return
        for path in sorted(self._root.iterdir()):
            if not path.is_dir() or path.name.startswith("."):
                continue
            skill_file = path / "SKILL.md"
            if not skill_file.is_file():
                continue
            try:
                name, description = _parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            except OSError:
                continue
            self._skills[name or path.name] = SkillMeta(
                name=name or path.name,
                description=description,
                path=path.resolve(),
            )

    def list_skills(self) -> list[SkillMeta]:
        return list(self._skills.values())

    def list_text(self) -> str:
        if not self._skills:
            return "当前没有可用技能。"
        return "可用技能：\n" + "\n".join(
            f"- {item.name}：{item.description}" for item in self._skills.values()
        )

    def _meta(self, name: str) -> SkillMeta | None:
        if not _safe_name(name):
            return None
        return self._skills.get(name)

    def activate(self, name: str) -> str:
        meta = self._meta(name)
        if meta is None:
            return f"技能不存在：{name}"
        body = (meta.path / "SKILL.md").read_text(encoding="utf-8")
        self._active[name] = time.time()
        return body[:MAX_BODY_CHARS]

    def read(self, name: str, page: int = 0) -> str:
        meta = self._meta(name)
        if meta is None:
            return f"技能不存在：{name}"
        files = (
            sorted((meta.path / "references").glob("*.md"))
            if (meta.path / "references").is_dir()
            else []
        )
        if not files:
            return "这个技能没有额外的参考资料。"
        page = max(0, min(page, len(files) - 1))
        text = files[page].read_text(encoding="utf-8")
        return text[:PAGE_CHARS]

    def active_names(self, now: float | None = None) -> list[str]:
        moment = time.time() if now is None else now
        expired = [name for name, at in self._active.items() if moment - at > ACTIVE_TTL_SECONDS]
        for name in expired:
            self._active.pop(name, None)
            log.info("skill auto-unloaded: %s", name)
        return list(self._active)

    def is_active(self, name: str) -> bool:
        return name in self.active_names()


def _safe_name(name: str) -> bool:
    return bool(name) and not re.search(r"[\\/]|\.\.", name) and len(name) <= 64


def _parse_frontmatter(text: str) -> tuple[str, str]:
    name = ""
    description = ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip()
    return name, description
