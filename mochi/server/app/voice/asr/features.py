"""音频特征：音量与语速修正情绪刺激强度（T4-13）。"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["AudioFeatures", "analyze_pcm", "pcm_rms"]


@dataclass(frozen=True)
class AudioFeatures:
    rms: float
    duration_s: float
    speech_rate: float
    magnitude_scale: float

    def to_payload(self) -> dict[str, float]:
        return {
            "rms": round(self.rms, 4),
            "duration_s": round(self.duration_s, 3),
            "speech_rate": round(self.speech_rate, 3),
            "magnitude_scale": round(self.magnitude_scale, 3),
        }


def pcm_rms(pcm: bytes) -> float:
    """PCM16 little-endian 的 RMS（0–1）。"""
    if len(pcm) < 2:
        return 0.0
    import numpy as np

    audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    return float(math.sqrt(float(np.mean(audio * audio))))


def analyze_pcm(pcm: bytes, sample_rate: int = 16_000) -> AudioFeatures:
    """用音量与能量段估算幅度倍率；大声与低语至少相差 20%。"""
    duration = len(pcm) / 2 / sample_rate if sample_rate else 0.0
    rms = pcm_rms(pcm)
    energy = min(1.0, rms / 0.06)
    # 语速用"单位时间内的能量过零段"近似，不做音素级对齐
    import numpy as np

    audio = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype=np.int16).astype(np.float32) / 32768.0
    if audio.size:
        frame = max(1, int(sample_rate * 0.05))
        peaks = 0
        for start in range(0, audio.size, frame):
            if float(np.mean(np.abs(audio[start : start + frame]))) > 0.02:
                peaks += 1
        speech_rate = peaks / max(1.0, duration)
    else:
        speech_rate = 0.0
    rate_scale = min(0.15, max(-0.1, (speech_rate - 8.0) * 0.01))
    magnitude_scale = max(0.6, min(1.6, 0.8 + 0.5 * energy + rate_scale))
    return AudioFeatures(
        rms=rms,
        duration_s=duration,
        speech_rate=speech_rate,
        magnitude_scale=magnitude_scale,
    )
