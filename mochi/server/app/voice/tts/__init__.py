"""TTS 抽象与 edge-tts 实现。"""

from .base import TTSProvider
from .edge_tts import EdgeTTSProvider, format_pitch, format_rate, format_volume

__all__ = [
    "EdgeTTSProvider",
    "TTSProvider",
    "format_pitch",
    "format_rate",
    "format_volume",
]
