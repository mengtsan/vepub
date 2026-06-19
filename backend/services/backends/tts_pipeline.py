"""
通用 HuggingFace TTS 後端（transformers pipeline）。
支援大多數上傳到 HF 的 TTS 模型（Kokoro、SpeechT5、Parler 等）。
輸出一律轉為 int16 PCM 串流（與 OmniVoice 相同格式）。
"""
from __future__ import annotations
import asyncio
import io
import numpy as np


class TransformersTTSBackend:
    def __init__(self, model_id: str, local_path: str, device: str = "auto"):
        self.model_id = model_id
        self._local_path = local_path
        self._device = device
        self._pipeline = None
        self.sample_rate = 22050   # 會在 load 後更新

    async def load(self) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._load_sync)

    def _load_sync(self) -> None:
        from transformers import pipeline as hf_pipeline
        import torch

        device = 0 if (self._device == "cuda" and torch.cuda.is_available()) else -1
        source = self._local_path if self._local_path else self.model_id

        self._pipeline = hf_pipeline(
            "text-to-speech",
            model=source,
            device=device,
        )
        # 更新實際 sample rate
        if hasattr(self._pipeline, "sampling_rate"):
            self.sample_rate = self._pipeline.sampling_rate
        print(f"[tts_pipeline] 載入完成: {source} @ {self.sample_rate}Hz")

    async def unload(self) -> None:
        import gc
        self._pipeline = None
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def is_loaded(self) -> bool:
        return self._pipeline is not None

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        instruct: str | None = None,
        speed: float = 1.0,
        **kwargs,
    ):
        if not self.is_loaded():
            await self.load()

        from services.gpu_manager import gpu_manager
        loop = asyncio.get_running_loop()
        await gpu_manager.acquire_gpu('tts')
        try:
            output = await loop.run_in_executor(None, self._synth_sync, text)
        finally:
            gpu_manager.release_gpu()

        audio = output["audio"]
        if isinstance(audio, (list, np.ndarray)):
            audio_np = np.array(audio, dtype=np.float32).flatten()
        else:
            audio_np = np.frombuffer(audio, dtype=np.float32)

        audio_int16 = (audio_np * 32767).astype(np.int16)
        chunk_samples = int(self.sample_rate * 0.2)
        for i in range(0, len(audio_int16), chunk_samples):
            yield audio_int16[i:i + chunk_samples].tobytes()
            await asyncio.sleep(0)

    def _synth_sync(self, text: str) -> dict:
        return self._pipeline(text)
