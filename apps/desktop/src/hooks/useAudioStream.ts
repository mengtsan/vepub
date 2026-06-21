import { useEffect, useRef, useCallback } from "react";
import { toast } from "sonner";
import { usePlayerStore } from "@/stores/player";
import { useReaderStore } from "@/stores/reader";

import { BACKEND_WS_URL, PREFETCH } from "@/lib/constants";
const BACKEND_WS = `${BACKEND_WS_URL}/v1/audio/stream`;
const SAMPLE_RATE = 24000;

export function useAudioStream(onChapterEnded?: () => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const sentQueueRef = useRef<number[]>([]);
  const activeSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const hasSentLastSentenceRef = useRef<boolean>(false);

  // 實體音訊高亮同步與手動跳轉控制 refs
  const highlightTimeoutIdsRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const lastScheduledIndexRef = useRef<number | null>(null);
  const currentReceivingIndexRef = useRef<number | null>(null);
  const isAutoTickingRef = useRef<boolean>(false);

  // §5.4 WS 協定：request_id 過濾與 cancel 支援
  const reqSeqRef = useRef<number>(0);
  const currentRequestIdRef = useRef<string | null>(null);
  const ignoringChunksRef = useRef<boolean>(false);

  const {
    isPlaying,
    sentences,
    currentSentenceIndex,
    speed,
    ttsMode,
    refAudioPath,
    refText,
    instruct,
    numStep,
    duration,
    language,
    _setCurrentIndex,
    setWs,
    setIsLoading,
  } = usePlayerStore();

  // 初始化 AudioContext 與 GainNode 實例
  useEffect(() => {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    const ctx = new AudioContextClass({ sampleRate: SAMPLE_RATE });
    audioCtxRef.current = ctx;

    const gainNode = ctx.createGain();
    gainNode.gain.value = useReaderStore.getState().volume / 100;
    gainNode.connect(ctx.destination);
    gainNodeRef.current = gainNode;

    return () => {
      ctx.close();
    };
  }, []);

  // 停止所有當前正在播送的音訊節點與高亮排程
  const stopAllAudio = useCallback(() => {
    activeSourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch (e) {
        // 忽略已經停止播放的 source 報錯
      }
    });
    activeSourcesRef.current = [];
    nextPlayTimeRef.current = 0;

    highlightTimeoutIdsRef.current.forEach(clearTimeout);
    highlightTimeoutIdsRef.current = [];
    lastScheduledIndexRef.current = null;
  }, []);

  // 發送句子給後端進行語音合成，攜帶遞增 request_id
  const sendSentence = useCallback((ws: WebSocket, index: number) => {
    if (index >= sentences.length) return;
    if (ws.readyState !== WebSocket.OPEN) return;

    reqSeqRef.current += 1;
    const request_id = String(reqSeqRef.current);
    currentRequestIdRef.current = request_id;
    ignoringChunksRef.current = false;

    const payload: Record<string, unknown> = {
      text: sentences[index].text,
      sentence_index: index,
      speed,
      num_step: numStep,
      request_id,
    };

    if (ttsMode === "clone" && refAudioPath) {
      payload.ref_audio_path = refAudioPath;
      if (refText) payload.ref_text = refText;
    } else if (ttsMode === "design" && instruct) {
      payload.instruct = instruct;
    } else {
      // 自動模式：角色配音（Phase 2）——該句若已歸屬角色，帶上 speaker 錨定鍵
      // 與其聲線 instruct；後端首句以 instruct 取聲、之後重用同一聲線。
      const s = sentences[index];
      if (s.speaker) {
        payload.speaker = s.speaker;
        if (s.voiceInstruct) payload.instruct = s.voiceInstruct;
      }
    }

    if (duration !== null) {
      payload.duration = duration;
    }

    // 朗讀語系：null = 交後端自動偵測；指定時優先採用
    if (language) {
      payload.language = language;
    }

    ws.send(JSON.stringify(payload));
    sentQueueRef.current.push(index);
  }, [sentences, speed, ttsMode, refAudioPath, refText, instruct, numStep, duration, language]);

  // 處理文字訊息（sentence_start/end/cancelled/error），依 request_id 過濾過期回應
  const handleTextMessage = useCallback((msg: any, ws: WebSocket) => {
    if (msg.type === "sentence_start") {
      if (msg.request_id && msg.request_id !== currentRequestIdRef.current) {
        // 此 start 屬於已過期請求，忽略後續 PCM chunks
        ignoringChunksRef.current = true;
        return;
      }
      ignoringChunksRef.current = false;
      currentReceivingIndexRef.current = msg.index;
    }
    if (msg.type === "sentence_end") {
      if (msg.request_id && msg.request_id !== currentRequestIdRef.current) {
        return;  // 過期
      }
      if (msg.index === sentences.length - 1) {
        hasSentLastSentenceRef.current = true;
      }
      const lastSent = sentQueueRef.current[sentQueueRef.current.length - 1] ?? msg.index;
      if (lastSent + 1 < sentences.length) {
        sendSentence(ws, lastSent + 1);
      }
    }
    if (msg.type === "cancelled") {
      // 後端確認 cancel 生效，不需要做任何事
      return;
    }
    if (msg.type === "error") {
      console.error("[WS] 後端回傳錯誤:", msg.message);
      toast.error(msg.message || "語音合成發生錯誤");
    }
  }, [sentences, sendSentence]);

  // 處理收到的 PCM 音訊二進位資料並排程播放
  const handlePCMChunk = useCallback(async (buffer: ArrayBuffer, sentenceIndex: number) => {
    // 若當前接收的是過期請求的資料，直接丟棄
    if (ignoringChunksRef.current) return;

    const ctx = audioCtxRef.current;
    if (!ctx) return;

    setIsLoading(false);

    if (ctx.state === "suspended") {
      await ctx.resume();
    }

    const int16 = new Int16Array(buffer);
    const float32 = new Float32Array(int16.length);

    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0;
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE);
    audioBuffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;

    if (gainNodeRef.current) {
      source.connect(gainNodeRef.current);
    } else {
      source.connect(ctx.destination);
    }

    activeSourcesRef.current.push(source);
    source.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter((s) => s !== source);
      if (hasSentLastSentenceRef.current && activeSourcesRef.current.length === 0) {
        hasSentLastSentenceRef.current = false;
        onChapterEnded?.();
      }
    };

    const startTime = Math.max(nextPlayTimeRef.current, ctx.currentTime);
    source.start(startTime);
    nextPlayTimeRef.current = startTime + audioBuffer.duration;

    if (sentenceIndex !== null && sentenceIndex !== lastScheduledIndexRef.current) {
      lastScheduledIndexRef.current = sentenceIndex;
      const delayMs = Math.max(0, (startTime - ctx.currentTime) * 1000);
      const timeoutId = setTimeout(() => {
        isAutoTickingRef.current = true;
        _setCurrentIndex(sentenceIndex);
      }, delayMs);
      highlightTimeoutIdsRef.current.push(timeoutId);
    }
  }, [onChapterEnded, _setCurrentIndex, setIsLoading]);

  const connectAndPlay = useCallback(() => {
    // 已有連線「正在建立(CONNECTING)或已開啟(OPEN)」就不再開新的。
    // 從非 0 句開始播放時，isPlaying 與 currentSentenceIndex 會同一次 render 一起變，
    // 使 Effect A 與 Effect B 都呼叫 connectAndPlay；若只擋 OPEN，第一條還在 CONNECTING
    // 時會被放行而開出第二條 WS，造成兩股音訊交錯（聽起來像往回跳）。
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
        wsRef.current.readyState === WebSocket.CONNECTING)
    ) {
      return;
    }

    stopAllAudio();
    sentQueueRef.current = [];
    hasSentLastSentenceRef.current = false;
    ignoringChunksRef.current = false;
    currentRequestIdRef.current = null;

    setIsLoading(true);

    const ws = new WebSocket(BACKEND_WS);
    ws.binaryType = "arraybuffer";
    wsRef.current = ws;
    setWs(ws);

    if (audioCtxRef.current) {
      nextPlayTimeRef.current = audioCtxRef.current.currentTime;
    }

    ws.onopen = () => {
      // 從 store 即時讀取，避免 closure 捕捉到舊的 currentSentenceIndex
      const startIdx = usePlayerStore.getState().currentSentenceIndex;
      console.log("[WS] 連線已建立，開始發送起始句子索引:", startIdx);
      for (let i = startIdx; i < Math.min(startIdx + PREFETCH, sentences.length); i++) {
        sendSentence(ws, i);
      }
    };

    ws.onmessage = (event) => {
      if (typeof event.data === "string") {
        try {
          handleTextMessage(JSON.parse(event.data), ws);
        } catch (e) {
          console.error("解析 WebSocket 文字訊息失敗:", e);
        }
      } else {
        const sentenceIndex = currentReceivingIndexRef.current;
        if (sentenceIndex !== null) {
          handlePCMChunk(event.data, sentenceIndex);
        }
      }
    };

    ws.onerror = (e) => {
      console.error("WebSocket 發生異常:", e);
      setIsLoading(false);
    };

    ws.onclose = () => {
      console.log("[WS] 連線已關閉");
      wsRef.current = null;
      setWs(null);
      setIsLoading(false);
    };
  }, [sentences, sendSentence, handleTextMessage, handlePCMChunk, stopAllAudio, setWs, setIsLoading]);

  const resumeAudio = useCallback(async () => {
    const ctx = audioCtxRef.current;
    if (ctx && ctx.state === "suspended") {
      try {
        await ctx.resume();
        console.log("[AudioContext] 經由使用者事件成功解凍，狀態為:", ctx.state);
      } catch (e) {
        console.error("解凍 AudioContext 失敗:", e);
      }
    }
  }, []);

  const changeVolume = useCallback((val: number) => {
    if (gainNodeRef.current) {
      gainNodeRef.current.gain.value = val / 100;
    }
  }, []);

  // 監聽播放狀態變更
  useEffect(() => {
    if (isPlaying) {
      connectAndPlay();
    } else {
      if (wsRef.current) {
        wsRef.current.close();
      }
      stopAllAudio();
      setIsLoading(false);
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      stopAllAudio();
      setIsLoading(false);
    };
  }, [isPlaying, connectAndPlay, stopAllAudio, setIsLoading]);

  // 監聽當前句子索引的改變（用來辨識使用者手動點擊跳轉）
  useEffect(() => {
    if (!isPlaying) return;

    if (isAutoTickingRef.current) {
      // 這是播音排程自動觸發的高亮更新，不需重連
      isAutoTickingRef.current = false;
      return;
    }

    // 使用者手動跳轉：優先用 cancel 訊息取代關閉 WS 重連
    console.log("[useAudioStream] 偵測到使用者手動跳轉至句子:", currentSentenceIndex);

    stopAllAudio();
    sentQueueRef.current = [];
    hasSentLastSentenceRef.current = false;

    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      // 送出 cancel，後端停止當前合成；直接在既有連線上送新請求
      ws.send(JSON.stringify({ type: "cancel" }));
      setIsLoading(true);
      const startIdx = usePlayerStore.getState().currentSentenceIndex;
      for (let i = startIdx; i < Math.min(startIdx + PREFETCH, sentences.length); i++) {
        sendSentence(ws, i);
      }
    } else {
      connectAndPlay();
    }
  }, [currentSentenceIndex, isPlaying, sentences, sendSentence, connectAndPlay, stopAllAudio, setIsLoading]);

  return {
    resumeAudio,
    changeVolume,
  };
}
