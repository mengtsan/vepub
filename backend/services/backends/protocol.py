"""
三類 AI 功能的共用 Protocol 介面（duck-typed，無需繼承）。
任何實作只要符合方法簽名即可作為後端使用。
"""
from typing import AsyncIterator, Protocol, runtime_checkable


@runtime_checkable
class TTSBackend(Protocol):
    model_id: str

    async def load(self) -> None: ...
    async def unload(self) -> None: ...
    def is_loaded(self) -> bool: ...
    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        instruct: str | None = None,
        speed: float = 1.0,
        **kwargs,
    ) -> AsyncIterator[bytes]: ...


@runtime_checkable
class ImageBackend(Protocol):
    model_id: str

    async def load(self) -> None: ...
    async def unload(self) -> None: ...
    async def is_ready(self) -> bool: ...
    async def generate(
        self,
        text: str,
        character_desc: str = "",
        width: int = 1024,
        height: int = 1024,
        seed: int = -1,
        prompt_prefix: str = "",
        on_progress=None,
    ) -> tuple[bytes, str, bool]: ...
