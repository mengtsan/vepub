"""
OmniVoice TTS 引擎封裝。
支援三種後端：mlx / cuda / cpu
對外暴露統一的 synthesize_stream() 非同步產生器與 load() / unload()。

模型權重來源由建構時的 local_path 決定（來自 model_registry 的 local_path）；
模型切換在 backend 層完成（router 重建 OmniVoiceBackend），引擎本身不持有模型 ID。

完整支援 OmniVoice 官方三種推理模式：
  - Voice Cloning（聲音複製）：ref_audio + 選填 ref_text
  - Voice Design（聲音設計）：instruct 自然語言描述
  - Auto（自動）：使用模型預設聲音
"""
import asyncio
import logging
import re

import numpy as np

logger = logging.getLogger(__name__)

# 字元區段 → OmniVoice 語言 ID。用於在呼叫端未指定 language 時依文字內容判斷，
# 避免漢字在「語言不可知」模式下被誤判成粵語(yue)等方言。
_RE_KANA   = re.compile(r"[぀-ゟ゠-ヿ]")  # 平假名 / 片假名 → 日文
_RE_HANGUL = re.compile(r"[가-힣]")               # 諺文 → 韓文
_RE_HAN    = re.compile(r"[一-鿿㐀-䶿]")  # 漢字 → 中文(普通話)
_RE_LATIN  = re.compile(r"[A-Za-z]")


def detect_language(text: str) -> str | None:
    """依文字內容粗略判斷 OmniVoice 語言 ID；無法判斷時回傳 None（交模型自動偵測）。

    順序很重要：日文同時含假名與漢字，必須先驗假名，否則會被當成中文。
    """
    if not text:
        return None
    if _RE_KANA.search(text):
        return "ja"
    if _RE_HANGUL.search(text):
        return "ko"
    if _RE_HAN.search(text):
        return "zh"      # 普通話（111k hr 訓練），明確指定避免落入粵語
    if _RE_LATIN.search(text):
        return "en"
    return None


# 對白標記：中日全形引號。用於 Phase 1 旁白/對白分流——含引號者視為對白，
# 其餘為旁白。中文小說常省略「某某說」，故先以引號這個最穩定的線索粗分。
_RE_DIALOGUE = re.compile(r"[「『“]")


def classify_segment(text: str) -> str:
    """將一句粗分為 'dialogue'（含引號）或 'narrator'（旁白）。"""
    return "dialogue" if _RE_DIALOGUE.search(text or "") else "narrator"


class TTSEngine:
    def __init__(self, device: str = "auto", local_path: str | None = None):
        self.device = device
        # 模型權重所在本地目錄（由 registry 的 local_path 傳入）；
        # 為 None 或不完整時退回 HF repo id，由 huggingface_hub 自動處理快取。
        self.local_path = local_path
        self.model = None
        self.sample_rate = 24000
        self._lock = asyncio.Lock()
        # 自我錨定聲線（Phase 0+1）：role('narrator'/'dialogue') → VoiceClonePrompt。
        # Auto 模式下首次合成某 role 後即固定其聲線，後續重用以保持音色一致。
        self._voice_anchors: dict[str, object] = {}

    def reset_voice_anchors(self) -> None:
        """清除已錨定的旁白/對白聲線，下次合成重新隨機。"""
        self._voice_anchors.clear()
        logger.info("已重置自我錨定聲線（旁白/對白）")

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

    def _resolve_model_source(self) -> str:
        """決定模型載入來源：本地目錄完整則用之，否則退回 HF repo id（自動快取）。"""
        import os
        from pathlib import Path

        if self.local_path \
           and os.path.exists(os.path.join(self.local_path, "config.json")) \
           and os.path.exists(os.path.join(self.local_path, "model.safetensors")):
            src = Path(self.local_path).as_posix()
            logger.info("自本地目錄載入 OmniVoice: %s", src)
            return src

        logger.info("本地未偵測到完整權重，改用 HF repo（自動快取）: k2-fsa/OmniVoice")
        return "k2-fsa/OmniVoice"

    def _load_torch(self):
        """
        載入 PyTorch 版本模型（適用於 CUDA 與 CPU）
        """
        import torch
        from omnivoice import OmniVoice

        device_map = "cuda:0" if self.device == "cuda" else "cpu"
        dtype = torch.float16 if self.device == "cuda" else torch.float32

        self.model = OmniVoice.from_pretrained(
            self._resolve_model_source(),
            device_map=device_map,
            dtype=dtype,
        )

    def _load_mlx(self):
        """
        載入 MLX 版本模型（適用於 Apple Silicon）
        """
        model_source = self._resolve_model_source()
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

    def _unload_model_memory(self):
        """
        釋放目前已載入的模型記憶體資源。
        """
        import gc

        # 錨定聲線是依當前模型 tokenizer 建立的，換模型/卸載時必須一併清除。
        self._voice_anchors.clear()

        if self.model is not None:
            logger.info("正在卸載 TTS 模型")
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
        language: str | None = None,
        speaker: str | None = None,
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
                    text, ref_audio_path, ref_text, instruct, speed, duration, num_step, language, speaker
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
        language: str | None = None,
        speaker: str | None = None,
    ) -> np.ndarray:
        """
        呼叫模型進行語音合成的同步實作，回傳 numpy float32 陣列。
        根據提供的參數自動決定使用 Voice Cloning / Voice Design / Auto 模式。

        speaker 為錨定鍵（Phase 2 角色配音）：同一角色固定一個聲線；
        instruct 在該角色「首句」作為聲線種子（如 'female, young adult'），錨定後重用。
        """
        from omnivoice.models.omnivoice import OmniVoiceGenerationConfig

        # num_step 屬於 generation_config，並非 generate() 的頂層參數；
        # 直接以 num_step= 傳入會被 **kwargs 吞掉而完全無效。
        kwargs: dict = {
            "text": text,
            "generation_config": OmniVoiceGenerationConfig(num_step=num_step),
        }

        # 語言決議優先序：單次請求 language ＞ 全域強制語系 ＞ 文字內容自動偵測。
        # None 會落入模型「語言不可知」模式，漢字可能被誤判成粵語(yue)，故中文須明確帶 'zh'。
        from services.tts_settings import get_forced_language
        forced = get_forced_language()
        if language:
            lang, src = language, "請求指定"
        elif forced:
            lang, src = forced, "全域強制"
        else:
            lang, src = detect_language(text), "自動偵測"
        if lang:
            kwargs["language"] = lang
            logger.debug("語言: %s（%s）", lang, src)

        # 待錨定的鍵（None 表示本句不需要建立錨定）。
        pending_anchor_key: str | None = None

        # Voice Cloning 模式：提供參考音訊（直接複製，不走自我錨定）
        if ref_audio_path:
            kwargs["ref_audio"] = ref_audio_path
            if ref_text:
                kwargs["ref_text"] = ref_text
            logger.debug("模式: Voice Cloning | ref_audio=%s...", ref_audio_path[:30])

        # Voice Design / Auto：以 speaker（角色，Phase 2）或旁白/對白（Phase 1）為鍵
        # 自我錨定聲線。instruct（角色聲線設計或使用者描述）作為該鍵「首句」的聲線種子，
        # 錨定後即改用 voice_clone_prompt 重用，確保同一角色音色一致。
        else:
            from services.tts_settings import get_settings as _tts_get
            key = speaker or classify_segment(text)
            if _tts_get().voice_consistency:
                anchor = self._voice_anchors.get(key)
                if anchor is not None:
                    kwargs["voice_clone_prompt"] = anchor
                    logger.debug("聲線: %s（重用錨定）", key)
                else:
                    if instruct:
                        kwargs["instruct"] = instruct
                    pending_anchor_key = key
                    logger.debug("聲線: %s（首次%s，待錨定）", key, "/instruct" if instruct else "")
            elif instruct:
                kwargs["instruct"] = instruct
                logger.debug("模式: Voice Design | instruct='%s'", instruct)
            else:
                logger.debug("模式: Auto（一致性關閉，每句隨機）")

        # 若設定固定輸出時長，優先使用（會覆蓋 speed）
        if duration is not None:
            kwargs["duration"] = duration
        else:
            kwargs["speed"] = speed

        # generate() 回傳 list[np.ndarray]（每個元素對應一句輸入文字）。
        # 單句合成只取第一個元素，避免被包成 (1, T) 形狀。
        audio = self.model.generate(**kwargs)

        if isinstance(audio, (list, tuple)):
            audio = audio[0] if audio else np.zeros(0, dtype=np.float32)

        # 確保回傳 numpy float32 陣列
        if hasattr(audio, "numpy"):
            audio = audio.numpy()
        audio = np.asarray(audio, dtype=np.float32)

        # 建立錨定：首次該鍵的輸出夠長（≥0.5s）才拿來當聲線參考，避免用過短片段。
        if pending_anchor_key is not None and len(audio) >= int(self.sample_rate * 0.5):
            self._anchor_voice(pending_anchor_key, audio, text)

        return audio

    def _anchor_voice(self, role: str, audio: np.ndarray, text: str) -> None:
        """用一段合成輸出建立可重用的 VoiceClonePrompt，固定該 role 之後的聲線。"""
        try:
            import torch
            prompt = self.model.create_voice_clone_prompt(
                ref_audio=(torch.from_numpy(np.ascontiguousarray(audio)), self.sample_rate),
                ref_text=text,
            )
            self._voice_anchors[role] = prompt
            logger.info("已錨定 %s 聲線（來源句長 %.1fs）", role, len(audio) / self.sample_rate)
        except Exception as e:
            logger.warning("錨定 %s 聲線失敗（後續仍會重試）: %s", role, e)
