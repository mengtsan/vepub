import asyncio
import gc
import logging
import torch
from typing import Literal

logger = logging.getLogger(__name__)

TaskType = Literal[
    'none', 'tts',
    'illustration', 'illustration_sdxl', 'illustration_zimage',
    'analysis'
]

class GPUManager:
    """
    VRAM 仲裁器。VRAM 預算 25.7 GB，各引擎估計用量：
      TTS       ~4 GB
      SDXL      ~8 GB
      ZImage   ~21 GB
      27B LLM  ~16 GB

    鎖策略：
      lock      — TTS ↔ ZImage/Wan 互斥（ZImage 21+TTS 4 = 25 GB，接近上限）
      illus_lock — 插圖序列化（任何兩個插圖任務不得同時運行）

      SDXL (8 GB) + TTS (4 GB) = 12 GB → 可共存，SDXL 不持 lock。
      ZImage (21 GB) + TTS (4 GB) = 25 GB → 接近上限，必須互斥，ZImage 持 lock。

    分析任務（27B 16 GB）不持互斥鎖（TTS 4+16 = 20 GB OK），
    但透過 _analysis_done Event 讓插圖等待分析結束。
    """

    def __init__(self):
        self.lock       = asyncio.Lock()   # TTS ↔ ZImage 互斥
        self.illus_lock = asyncio.Lock()   # 插圖序列化（防止兩個插圖同時跑）
        self.current_task: TaskType = 'none'
        self.tts_engine = None
        self.illustration_engine = None
        # 分析期間 cleared；分析結束後 set → 插圖 wait() 不阻塞
        self._analysis_done = asyncio.Event()
        self._analysis_done.set()

    def register_engines(self, tts_engine, illustration_engine):
        self.tts_engine = tts_engine
        self.illustration_engine = illustration_engine

    async def acquire_gpu(self, task_type: TaskType):
        """
        請求 GPU VRAM 資源。
        task_type 細分：
          'illustration_sdxl'   — SDXL，可與 TTS 共存
          'illustration_zimage' — ZImage，與 TTS 互斥
          'illustration'        — 向下相容，行為等同 illustration_zimage
        """
        if task_type == 'analysis':
            # 卸載插圖模型（~8 GB）以騰空給 27B；TTS 可繼續
            if self.illustration_engine:
                logger.info("27B 分析啟動，卸載插圖模型")
                await self.illustration_engine.unload()
            self._analysis_done.clear()   # 通知插圖任務：請等待
            logger.info("角色分析啟動（TTS 正常可用）")
            return  # 不持 lock

        if task_type == 'tts':
            await self.lock.acquire()
            self.current_task = 'tts'
            logger.debug("GPU 鎖定成功: tts")
            return

        # 插圖任務：先驅逐 LLM server（SDXL 8+LLM 16+TTS 4 = 28 > 25.7）
        try:
            from services.llm_engine import stop_server_now
            await stop_server_now()
        except Exception:
            pass

        # 等待分析完成（asyncio.Event 取代 busy-wait）
        await self._analysis_done.wait()

        if task_type == 'illustration_sdxl':
            # SDXL 不持 lock → TTS 可同時進行
            await self.illus_lock.acquire()
            self.current_task = 'illustration_sdxl'
            logger.debug("GPU 鎖定成功: illustration_sdxl（TTS 可並行）")
        else:
            # ZImage / 向下相容 'illustration' → 持 lock，TTS 必須等待
            await self.illus_lock.acquire()
            await self.lock.acquire()
            self.current_task = task_type
            logger.debug("GPU 鎖定成功: %s（TTS 排隊等待）", task_type)

    def release_gpu(self):
        """
        釋放已持有的鎖。
        GC / empty_cache 只在插圖任務完成後執行；TTS 每句不做（避免拖慢句間銜接）。
        """
        task_type = self.current_task
        self.current_task = 'none'

        if task_type == 'tts':
            try: self.lock.release()
            except RuntimeError: pass

        elif task_type == 'illustration_sdxl':
            try: self.illus_lock.release()
            except RuntimeError: pass
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        elif task_type in ('illustration', 'illustration_zimage'):
            try: self.lock.release()
            except RuntimeError: pass
            try: self.illus_lock.release()
            except RuntimeError: pass
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

        logger.debug("GPU 鎖已釋放: %s", task_type)

    def end_analysis(self):
        """分析任務結束後呼叫，解除插圖等待。"""
        self._analysis_done.set()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        logger.info("角色分析結束，插圖功能已恢復")


# 全域單例實例
gpu_manager = GPUManager()
