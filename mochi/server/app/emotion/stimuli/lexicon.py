"""情感词典（Level 1 分析器，计划书 5.2.6a）。

刻意做小而准：它的用途不是"识别所有情绪"，而是给情感引擎提供
高频、方向明确的刺激样本。命中不了的文本交给 Level 2（轻量 LLM）。
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "Lexicon",
    "NEGATIONS",
    "load_lexicon",
]


@dataclass(frozen=True)
class Lexicon:
    """五类词典。"""

    praise: tuple[str, ...] = ()
    insult: tuple[str, ...] = ()
    sad: tuple[str, ...] = ()
    intimate: tuple[str, ...] = ()
    surprise: tuple[str, ...] = ()
    care: tuple[str, ...] = ()
    strong_praise: tuple[str, ...] = ()
    strong_insult: tuple[str, ...] = ()

    def all_words(self) -> tuple[str, ...]:
        return (
            self.praise
            + self.insult
            + self.sad
            + self.intimate
            + self.surprise
            + self.care
            + self.strong_praise
            + self.strong_insult
        )


# 否定词：出现在情感词前 2 个字内则极性反转
NEGATIONS: tuple[str, ...] = ("不", "别", "没", "无", "并不", "算不上", "不太")

# 默认词典（可被 data/lexicon.yaml 覆盖）
DEFAULT_LEXICON = Lexicon(
    praise=(
        "谢谢",
        "感谢",
        "好棒",
        "厉害",
        "真棒",
        "喜欢你",
        "辛苦了",
        "你真聪明",
        "优秀",
        "不错",
        "太好了",
        "完美",
        "可爱",
        "加油",
        "真乖",
        "聪明",
        "靠谱",
    ),
    insult=(
        "笨",
        "蠢",
        "滚",
        "闭嘴",
        "烦死",
        "没用",
        "讨厌你",
        "垃圾",
        "难看",
        "笨蛋",
        "滚开",
        "神经病",
        "傻",
        "烦人",
    ),
    sad=(
        "难过",
        "好累",
        "累了",
        "失败",
        "分手",
        "想哭",
        "难受",
        "痛苦",
        "郁闷",
        "沮丧",
        "心情不好",
        "压力好大",
        "撑不住",
        "好难受",
    ),
    intimate=(
        "抱抱",
        "摸摸头",
        "摸头",
        "摸摸",
        "晚安",
        "么么",
        "亲亲",
        "贴贴",
        "蹭蹭",
        "抱一下",
        "牵手",
    ),
    surprise=("真的吗", "不会吧", "卧槽", "竟然", "居然", "惊呆", "天啊", "不会吧真的"),
    care=(
        "辛苦",
        "早点睡",
        "多休息",
        "保重",
        "注意身体",
        "别太累",
        "多喝热水",
        "别熬夜",
        "照顾好自己",
        "注意保暖",
    ),
    strong_praise=("最喜欢你", "爱死你了", "太棒了", "超厉害", "你是最好的"),
    strong_insult=("滚开", "去死", "蠢死了", "烦死了", "闭嘴吧"),
)


def load_lexicon() -> Lexicon:
    """加载词典：存在 ``data/lexicon.yaml`` 时覆盖默认值。"""
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parent / "data" / "lexicon.yaml"
    if not path.exists():
        return DEFAULT_LEXICON
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    kwargs: dict[str, tuple[str, ...]] = {}
    for key in DEFAULT_LEXICON.__dataclass_fields__:
        value = raw.get(key)
        if isinstance(value, list):
            kwargs[key] = tuple(str(item) for item in value)
    return Lexicon(**kwargs)
