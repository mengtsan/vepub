"""
TTS 路由。
POST /v1/audio/speech        → 回傳完整 WAV（小文字用）
WS   /v1/audio/stream        → WebSocket 串流 PCM chunks
GET  /v1/audio/hardware      → 目前硬體資訊

WebSocket 協定（客戶端 → 伺服器）：
  合成請求：
    { "text": "...", "sentence_index": 0, "speed": 1.0,
      "ref_audio_path": null, "ref_text": null, "instruct": null,
      "duration": null, "num_step": 32, "language": null, "request_id": "1" }
    （language 省略時後端依文字內容自動偵測：漢字→'zh'、假名→'ja'、拉丁→'en'）
  取消請求：
    { "type": "cancel" }

伺服器 → 客戶端：
  { "type": "sentence_start", "index": N, "request_id": "1" }
  <binary frames: PCM int16 24kHz mono>
  { "type": "sentence_end", "index": N, "duration_ms": M, "request_id": "1" }
  { "type": "cancelled", "index": N, "request_id": "1" }  ← cancel 生效時
  { "type": "error", "message": "...", "request_id": "1" }
"""
import asyncio
import json
import logging
import io
import wave

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.tts_engine import TTSEngine
from services.tts_settings import get_settings, update_settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/settings")
async def get_tts_settings():
    """取得 TTS 全域設定（目前含優先手動語系 forced_language）。"""
    return get_settings().model_dump()


@router.patch("/settings")
async def patch_tts_settings(patch: dict):
    """更新 TTS 全域設定。forced_language 設為 null/'auto' 即恢復自動偵測。"""
    try:
        return update_settings(patch).model_dump()
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/voice/reset")
async def reset_voice(request: Request):
    """清除自我錨定的旁白/對白聲線，下次合成重新隨機取聲。"""
    backend = getattr(request.app.state, "tts", None)
    engine = getattr(backend, "_engine", backend)
    if engine and hasattr(engine, "reset_voice_anchors"):
        engine.reset_voice_anchors()
        return {"status": "ok"}
    return {"status": "noop"}


class SpeechRequest(BaseModel):
    """單次語音合成請求（REST API 用）"""
    input: str
    speed: float = 1.0
    sentence_index: int = 0
    ref_audio_path: str | None = None
    ref_text: str | None = None
    instruct: str | None = None
    duration: float | None = None
    num_step: int = 32
    language: str | None = None   # None = 後端依文字內容自動偵測（中文→'zh'）
    speaker: str | None = None    # 說話者錨定鍵（角色配音）；None = 旁白/對白自動分流


@router.post("/speech")
async def create_speech(req: SpeechRequest, request: Request):
    """合成單句文字並回傳完整 WAV 音訊。"""
    tts: TTSEngine = request.app.state.tts
    chunks = []
    async for chunk in tts.synthesize_stream(
        text=req.input,
        ref_audio_path=req.ref_audio_path,
        ref_text=req.ref_text,
        instruct=req.instruct,
        speed=req.speed,
        duration=req.duration,
        num_step=req.num_step,
        language=req.language,
        speaker=req.speaker,
    ):
        chunks.append(chunk)
    audio_bytes = b"".join(chunks)
    wav_bytes = _pcm_to_wav(audio_bytes, sample_rate=24000)
    return StreamingResponse(
        iter([wav_bytes]),
        media_type="audio/wav",
        headers={"X-Sentence-Index": str(req.sentence_index)},
    )


@router.websocket("/stream")
async def audio_stream(websocket: WebSocket):
    """
    WebSocket 串流 TTS。
    reader / synthesizer 兩個 task 並行：reader 持續監聽訊息（含 cancel），
    synthesizer 依序合成並送出 PCM chunks。
    cancel 訊息透過 cancel_event 通知 synthesizer 在下個 chunk 邊界停止送出。
    """
    await websocket.accept()
    tts: TTSEngine = websocket.app.state.tts
    logger.debug("WS 連線已建立")

    cancel_event = asyncio.Event()
    incoming: asyncio.Queue[dict | None] = asyncio.Queue()

    async def _reader():
        try:
            while True:
                data = await websocket.receive_json()
                if data.get("type") == "cancel":
                    cancel_event.set()
                    logger.debug("收到 cancel")
                else:
                    # 新合成請求同樣觸發 cancel，讓 synthesizer 停止當前句子
                    cancel_event.set()
                    await incoming.put(data)
        except WebSocketDisconnect:
            pass
        finally:
            await incoming.put(None)  # 通知 synthesizer 結束

    async def _synthesizer():
        try:
            while True:
                data = await incoming.get()
                if data is None:
                    break

                # 開始新請求前清除 cancel flag
                cancel_event.clear()

                request_id    = data.get("request_id")
                text          = data.get("text", "")
                sentence_index = data.get("sentence_index", 0)
                speed         = data.get("speed", 1.0)
                ref_audio_path = data.get("ref_audio_path") or None
                ref_text      = data.get("ref_text") or None
                instruct      = data.get("instruct") or None
                duration      = data.get("duration") or None
                num_step      = int(data.get("num_step", 32))
                language      = data.get("language") or None
                speaker       = data.get("speaker") or None

                logger.debug("合成 index=%d request_id=%s text='%s'",
                             sentence_index, request_id, text[:20])

                await websocket.send_text(json.dumps({
                    "type": "sentence_start",
                    "index": sentence_index,
                    "request_id": request_id,
                }))

                total_bytes = 0
                cancelled   = False
                try:
                    async for chunk in tts.synthesize_stream(
                        text=text,
                        ref_audio_path=ref_audio_path,
                        ref_text=ref_text,
                        instruct=instruct,
                        speed=speed,
                        duration=duration,
                        num_step=num_step,
                        language=language,
                        speaker=speaker,
                    ):
                        if cancel_event.is_set():
                            cancelled = True
                            break
                        await websocket.send_bytes(chunk)
                        total_bytes += len(chunk)
                except Exception as e:
                    logger.warning("TTS 合成失敗 index=%d: %s", sentence_index, e)
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "message": str(e),
                        "request_id": request_id,
                    }))
                    continue

                if cancelled:
                    logger.debug("已取消 index=%d", sentence_index)
                    await websocket.send_text(json.dumps({
                        "type": "cancelled",
                        "index": sentence_index,
                        "request_id": request_id,
                    }))
                else:
                    duration_ms = int(total_bytes / 2 / 24000 * 1000)
                    logger.debug("sentence_end index=%d duration=%dms", sentence_index, duration_ms)
                    await websocket.send_text(json.dumps({
                        "type": "sentence_end",
                        "index": sentence_index,
                        "duration_ms": duration_ms,
                        "request_id": request_id,
                    }))

        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error("synthesizer 異常: %s", e)
            try:
                await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
            except Exception:
                pass

    reader_task = asyncio.create_task(_reader())
    synth_task  = asyncio.create_task(_synthesizer())

    done, pending = await asyncio.wait(
        {reader_task, synth_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    logger.debug("WS 連線結束")


@router.get("/hardware")
async def get_hardware(request: Request):
    return request.app.state.hardware


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()
