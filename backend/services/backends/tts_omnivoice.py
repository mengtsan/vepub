"""
OmniVoice TTS 後端包裝器（實作 TTSBackend Protocol）。
直接委派給現有的 TTSEngine，不複製任何邏輯。
"""
from __future__ import annotations
from services.tts_engine import TTSEngine


class OmniVoiceBackend:
    model_id = "omnivoice"

    def __init__(self, engine: TTSEngine):
        self._engine = engine

    async def load(self) -> None:
        await self._engine.load()

    async def unload(self) -> None:
        await self._engine.unload()

    def is_loaded(self) -> bool:
        return self._engine.is_loaded()

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        instruct: str | None = None,
        speed: float = 1.0,
        duration: float | None = None,
        num_step: int = 32,
        language: str | None = None,
        **kwargs,
    ):
        async for chunk in self._engine.synthesize_stream(
            text=text,
            ref_audio_path=ref_audio_path,
            ref_text=ref_text,
            instruct=instruct,
            speed=speed,
            duration=duration,
            num_step=num_step,
            language=language,
        ):
            yield chunk
