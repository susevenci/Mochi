"""faster-whisper ASR（CPU int8，惰性加载）。

重依赖（ctranslate2/av）只在首次识别时导入；模型缺失时抛
``ASR_UNAVAILABLE``，由网关转成可读错误，文字输入不受影响。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from .base import ASRError, ASRResult

log = logging.getLogger(__name__)


class FasterWhisperASR:
    def __init__(
        self,
        *,
        model_size: str = "tiny",
        language: str = "zh",
        compute_type: str = "int8",
        initial_prompt: str = "",
        download_root: Path | None = None,
    ) -> None:
        self._model_size = model_size
        self._language = language
        self._compute_type = compute_type
        self._initial_prompt = initial_prompt
        self._download_root = download_root
        self._model: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except Exception as exc:  # noqa: BLE001 - 可选依赖
                raise ASRError("ASR_UNAVAILABLE", "faster-whisper 未安装") from exc
            try:
                self._model = await asyncio.to_thread(
                    WhisperModel,
                    self._model_size,
                    device="cpu",
                    compute_type=self._compute_type,
                    download_root=str(self._download_root) if self._download_root else None,
                )
            except Exception as exc:  # noqa: BLE001 - 模型下载/加载失败
                raise ASRError("ASR_MODEL_LOAD_FAILED", str(exc)) from exc
            log.info("faster-whisper loaded model=%s", self._model_size)
            return self._model

    async def transcribe(self, pcm: bytes, sample_rate: int = 16_000) -> ASRResult:
        if not pcm:
            return ASRResult(text="", language=self._language)
        model = await self._ensure_model()
        try:
            import numpy as np

            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, info = await asyncio.to_thread(
                model.transcribe,
                audio,
                language=self._language,
                vad_filter=True,
                beam_size=3,
                initial_prompt=self._initial_prompt or None,
                condition_on_previous_text=False,
            )
            text = "".join(segment.text for segment in segments).strip()
            duration = float(getattr(info, "duration", 0.0) or len(audio) / sample_rate)
            return ASRResult(text=text, language=self._language, duration_s=duration)
        except Exception as exc:  # noqa: BLE001 - 识别失败降级为字幕
            raise ASRError("ASR_FAILED", str(exc)) from exc

    async def aclose(self) -> None:
        self._model = None
