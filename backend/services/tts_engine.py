"""
OmniVoice TTS 引擎封裝。
支援三種後端：mlx / cuda / cpu
對外暴露統一的 synthesize_stream() 非同步產生器。
新增 load_specific() 與 unload() 支援執行期間動態切換模型。
完整支援 OmniVoice 官方三種推理模式：
  - Voice Cloning（聲音複製）：ref_audio + 選填 ref_text
  - Voice Design（聲音設計）：instruct 自然語言描述
  - Auto（自動）：使用模型預設聲音
"""
import asyncio
import logging
import numpy as np

logger = logging.getLogger(__name__)


class TTSEngine:
    def __init__(self, device: str = "auto"):
        self.device = device
        self.model = None
        self.sample_rate = 24000
        self._lock = asyncio.Lock()
        # 記錄目前已載入的模型 ID，供 /status 顯示使用
        self._loaded_model_id: str | None = None

    async def load(self):
        """
        非同步載入預設模型（在 startup 事件中呼叫）
        """
        from services.gpu_manager import gpu_manager
        await gpu_manager.acquire_gpu('tts')
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._load_sync)
        finally:
            gpu_manager.release_gpu()

    def _load_sync(self):
        """
        同步載入模型的內部實作
        """
        if self.device == "mlx":
            self._load_mlx()
        else:
            self._load_torch()

    def _load_torch(self):
        """
        載入 PyTorch 版本模型（適用於 CUDA 與 CPU）
        """
        import torch
        from omnivoice import OmniVoice
        from services.models_manager import get_current_model_id, MODEL_CONFIGS, set_engine_loaded_model_id
        from pathlib import Path

        device_map = "cuda:0" if self.device == "cuda" else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32

        model_id = get_current_model_id()
        model_source = "k2-fsa/OmniVoice"

        # 只有在本地專案目錄確實有模型檔案時才自本地載入，否則使用 repo_id 讓 Hugging Face 自動處理快取
        import os
        local_dir = MODEL_CONFIGS["official"]["local_dir"]
        if os.path.exists(os.path.join(local_dir, "config.json")) and \
           os.path.exists(os.path.join(local_dir, "model.safetensors")):
            model_source = Path(local_dir).as_posix()
            logger.info("自本地專案目錄載入官方模型: %s", model_source)
        else:
            logger.info("本地專案目錄未偵測到模型，自預設路徑載入 (Hugging Face 自動處理快取): %s", model_source)

        if model_id != "official":
            logger.info("已選取量化模型 %s（以官方 PyTorch 作為推理相容核心）", model_id)

        self.model = OmniVoice.from_pretrained(
            model_source,
            device_map=device_map,
            dtype=dtype,
        )
        self._loaded_model_id = model_id
        # 同步更新 models_manager 的全域載入狀態
        set_engine_loaded_model_id(model_id)

    def _load_mlx(self):
        """
        載入 MLX 版本模型（適用於 Apple Silicon）
        """
        from services.models_manager import get_current_model_id, MODEL_CONFIGS, set_engine_loaded_model_id
        from pathlib import Path
        import os

        model_id = get_current_model_id()
        model_source = "k2-fsa/OmniVoice"

        local_dir = MODEL_CONFIGS["official"]["local_dir"]
        if os.path.exists(os.path.join(local_dir, "config.json")) and \
           os.path.exists(os.path.join(local_dir, "model.safetensors")):
            model_source = Path(local_dir).as_posix()
            logger.info("自本地專案目錄載入 MLX 模型: %s", model_source)
        else:
            logger.info("本地專案目錄未偵測到模型，自預設路徑載入 MLX 模型: %s", model_source)

        if model_id != "official":
            logger.info("已選取量化模型 %s（以官方 MLX/MPS 作為推理相容核心）", model_id)

        try:
            from omnivoice_mlx import OmniVoiceMLX
            self.model = OmniVoiceMLX.from_pretrained(model_source)
        except ImportError:
            # 備用方案：使用 PyTorch MPS
            import torch
            from omnivoice import OmniVoice
            self.model = OmniVoice.from_pretrained(
                model_source,
                device_map="mps",
                dtype=torch.float16,
            )

        self._loaded_model_id = model_id
        set_engine_loaded_model_id(model_id)

    async def load_specific(self, model_id: str):
        """
        動態切換並載入指定的模型 ID（官方或量化版）。
        會先卸載現有模型以釋放記憶體，再重新載入。
        此操作為長時間阻塞操作，需在執行緒池中執行。
        """
        from services.gpu_manager import gpu_manager
        await gpu_manager.acquire_gpu('tts')
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._load_specific_sync, model_id)
        finally:
            gpu_manager.release_gpu()

    def _load_specific_sync(self, model_id: str):
        """
        同步切換模型的內部實作。
        """
        from services.models_manager import set_current_model_id

        # 更新資料庫中的選取模型設定
        set_current_model_id(model_id)

        # 先釋放現有模型記憶體
        self._unload_model_memory()

        # 重新載入（_load_sync 會自動讀取 get_current_model_id() 的設定）
        self._load_sync()
        logger.info("已成功切換並載入模型: %s", model_id)

    def _unload_model_memory(self):
        """
        釋放目前已載入的模型記憶體資源。
        """
        import gc
        from services.models_manager import set_engine_loaded_model_id

        if self.model is not None:
            logger.info("正在卸載模型: %s", self._loaded_model_id)
            # 嘗試呼叫模型自身的釋放方法（若有）
            if hasattr(self.model, "cpu"):
                try:
                    self.model.cpu()
                except Exception:
                    pass
            del self.model
            self.model = None
            gc.collect()

            # 若使用 CUDA，同時清空 GPU 記憶體
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass

        self._loaded_model_id = None
        set_engine_loaded_model_id("")  # "" = 明確卸載，區別於 None（啟動預設）
        logger.info("模型已從記憶體中卸載")

    async def unload(self):
        """
        非同步卸載目前載入的模型，釋放記憶體。
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._unload_model_memory)

    def is_loaded(self) -> bool:
        """
        回傳模型是否已載入至記憶體中。
        """
        return self.model is not None

    async def synthesize_stream(
        self,
        text: str,
        ref_audio_path: str | None = None,
        ref_text: str | None = None,
        instruct: str | None = None,
        speed: float = 1.0,
        duration: float | None = None,
        num_step: int = 32,
    ):
        """
        非同步產生 PCM 位元組（int16, 24kHz, 單聲道）。
        每次 yield 約 200ms 的音訊資料。

        支援 OmniVoice 三種推理模式：
        - Voice Cloning：提供 ref_audio_path（+選填 ref_text）
        - Voice Design：提供 instruct 自然語言聲音描述
        - Auto：不提供任何參考，使用模型預設聲音

        參數：
            text: 要合成的文字
            ref_audio_path: 參考音訊路徑（3-10秒，用於聲音複製）
            ref_text: 參考音訊的逐字稿（選填；省略時 Whisper 自動辨識）
            instruct: 聲音設計描述（如 "female, young adult, cheerful"）
            speed: 語速倍率（預設 1.0）
            duration: 強制輸出時長（秒）；設定後 speed 被忽略
            num_step: 擴散步數（32 高品質；16 快速推理）
        """
        from services.gpu_manager import gpu_manager

        if not self.is_loaded():
            logger.warning("TTS 模型未載入，正在自動重新加載...")
            await self.load()

        loop = asyncio.get_running_loop()
        await gpu_manager.acquire_gpu('tts')
        try:
            async with self._lock:
                audio_np = await loop.run_in_executor(
                    None,
                    self._synthesize_sync,
                    text, ref_audio_path, ref_text, instruct, speed, duration, num_step
                )
        finally:
            gpu_manager.release_gpu()

        # 切成小塊（chunk）進行串流
        chunk_samples = int(self.sample_rate * 0.2)  # 200ms 的採樣數
        audio_int16 = (audio_np.flatten() * 32767).astype(np.int16)

        for i in range(0, len(audio_int16), chunk_samples):
            chunk = audio_int16[i:i + chunk_samples]
            yield chunk.tobytes()
            await asyncio.sleep(0)  # 讓出事件迴圈，避免阻塞

    def _synthesize_sync(
        self,
        text: str,
        ref_audio_path: str | None,
        ref_text: str | None,
        instruct: str | None,
        speed: float,
        duration: float | None,
        num_step: int,
    ) -> np.ndarray:
        """
        呼叫模型進行語音合成的同步實作，回傳 numpy float32 陣列。
        根據提供的參數自動決定使用 Voice Cloning / Voice Design / Auto 模式。
        """
        kwargs: dict = {
            "text": text,
            "num_step": num_step,
        }

        # Voice Cloning 模式：提供參考音訊
        if ref_audio_path:
            kwargs["ref_audio"] = ref_audio_path
            if ref_text:
                kwargs["ref_text"] = ref_text
            logger.debug("模式: Voice Cloning | ref_audio=%s...", ref_audio_path[:30])

        # Voice Design 模式：提供聲音描述
        elif instruct:
            kwargs["instruct"] = instruct
            logger.debug("模式: Voice Design | instruct='%s'", instruct)

        # Auto 模式：使用模型預設聲音
        else:
            logger.debug("模式: Auto（使用模型預設聲音）")

        # 若設定固定輸出時長，優先使用（會覆蓋 speed）
        if duration is not None:
            kwargs["duration"] = duration
        else:
            kwargs["speed"] = speed

        audio = self.model.generate(**kwargs)

        # 確保回傳 numpy float32 陣列
        if hasattr(audio, "numpy"):
            return audio.numpy()
        return np.array(audio, dtype=np.float32)
