"""轻量能量 VAD（首版；保留 silero 接口）。

服务端只做端点辅助；push-to-talk 以用户松手为准，always_on 由前端
检测静音后发送 ``audio.in_end``。这样不把 VAD 延迟压进识别链路。
"""

from __future__ import annotations

from dataclasses import dataclass

from .features import pcm_rms

__all__ = ["EnergyVAD"]


@dataclass
class EnergyVAD:
    threshold: float = 0.012
    silence_seconds: float = 0.0
    speech_seconds: float = 0.0
    saw_speech: bool = False

    def process(self, pcm: bytes, sample_rate: int = 16_000) -> bool:
        duration = len(pcm) / 2 / sample_rate if sample_rate else 0.0
        if pcm_rms(pcm) >= self.threshold:
            self.saw_speech = True
            self.speech_seconds += duration
            self.silence_seconds = 0.0
        else:
            self.silence_seconds += duration
        return self.saw_speech

    @property
    def endpoint(self) -> bool:
        return self.saw_speech and self.speech_seconds > 0.2 and self.silence_seconds > 0.7

    def reset(self) -> None:
        self.silence_seconds = 0.0
        self.speech_seconds = 0.0
        self.saw_speech = False
