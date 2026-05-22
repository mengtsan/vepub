"""
TTS 路由。
POST /v1/audio/speech        → 回傳完整 WAV（小文字用）
WS   /v1/audio/stream        → WebSocket 串流 PCM chunks
GET  /v1/audio/hardware      → 目前硬體資訊

WebSocket 協定（客戶端請求格式）：
{
  "text": "要合成的文字",
  "sentence_index": 0,
  "speed": 1.0,
  "ref_audio_path": null,       // 選填：聲音複製參考音訊路徑
  "ref_text": null,             // 選填：參考音訊逐字稿（省略時自動辨識）
  "instruct": null,             // 選填：聲音設計描述
  "duration": null,             // 選填：固定輸出時長（秒）
  "num_step": 32                // 選填：擴散步數（32/16）
}
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from services.tts_engine import TTSEngine
import json

router = APIRouter()

class SpeechRequest(BaseModel):
    """單次語音合成請求（REST API 用）"""
    input: str                          # 要朗讀的文字
    speed: float = 1.0
    sentence_index: int = 0            # 供前端同步高亮用
    ref_audio_path: str | None = None  # 聲音複製參考音訊路徑
    ref_text: str | None = None        # 參考音訊逐字稿
    instruct: str | None = None        # 聲音設計描述
    duration: float | None = None      # 固定輸出時長（秒）
    num_step: int = 32                 # 擴散步數

@router.post("/speech")
async def create_speech(req: SpeechRequest, request: Request):
    """
    合成單句文字並回傳完整的 WAV 音訊檔案（適用於短文字）。
    """
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
    ):
        chunks.append(chunk)
    audio_bytes = b"".join(chunks)

    # 包裝成 WAV 格式
    wav_bytes = _pcm_to_wav(audio_bytes, sample_rate=24000)
    return StreamingResponse(
        iter([wav_bytes]),
        media_type="audio/wav",
        headers={"X-Sentence-Index": str(req.sentence_index)}
    )

@router.websocket("/stream")
async def audio_stream(websocket: WebSocket):
    """
    WebSocket 協定：
    客戶端傳送 JSON：
      {
        "text": "...",
        "sentence_index": 0,
        "speed": 1.0,
        "ref_audio_path": null,
        "ref_text": null,
        "instruct": null,
        "duration": null,
        "num_step": 32
      }
    伺服器回傳：
      - 二進位影格（binary frame）：PCM 位元組（int16, 24kHz, 單聲道）
      - 文字影格（text frame）：{ "type": "sentence_start", "index": 0 }
      - 文字影格（text frame）：{ "type": "sentence_end", "index": 0, "duration_ms": 1200 }
      - 文字影格（text frame）：{ "type": "done" }
    """
    await websocket.accept()
    tts: TTSEngine = websocket.app.state.tts
    print("[WS] 連線已建立 (accepted)")

    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")
            sentence_index = data.get("sentence_index", 0)
            speed = data.get("speed", 1.0)

            # 讀取語音模式相關參數
            ref_audio_path = data.get("ref_audio_path") or None
            ref_text = data.get("ref_text") or None
            instruct = data.get("instruct") or None
            duration = data.get("duration") or None
            num_step = int(data.get("num_step", 32))

            print(f"[WS] 收到合成請求: index={sentence_index}, speed={speed}, num_step={num_step}, text='{text[:20]}...'")

            # 通知前端開始播放此句
            await websocket.send_text(json.dumps({
                "type": "sentence_start",
                "index": sentence_index
            }))

            total_chunks = 0
            print(f"[WS] 開始調用 TTS 引擎...")
            async for chunk in tts.synthesize_stream(
                text=text,
                ref_audio_path=ref_audio_path,
                ref_text=ref_text,
                instruct=instruct,
                speed=speed,
                duration=duration,
                num_step=num_step,
            ):
                await websocket.send_bytes(chunk)
                total_chunks += 1
            print(f"[WS] TTS 合成完成，發送了 {total_chunks} 個 chunks")

            # 計算約略時長（PCM int16 24kHz mono）
            duration_ms = int(total_chunks * 200)

            await websocket.send_text(json.dumps({
                "type": "sentence_end",
                "index": sentence_index,
                "duration_ms": duration_ms
            }))
            print(f"[WS] 發送 sentence_end: index={sentence_index}, duration_ms={duration_ms}")

    except WebSocketDisconnect:
        print("[WS] 連線已斷開 (WebSocketDisconnect)")
    except Exception as e:
        print(f"[WS] 發生異常: {str(e)}")
        import traceback
        traceback.print_exc()

@router.get("/hardware")
async def get_hardware(request: Request):
    """
    獲取當前運作的硬體推論設定資訊。
    """
    return request.app.state.hardware

def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 24000) -> bytes:
    """
    將 PCM 二進位資料轉換為 WAV 檔案格式的位元組資料。
    """
    import wave, io
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # int16 佔 2 位元組
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)
    return buf.getvalue()
