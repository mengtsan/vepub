import { useEffect, useRef, useCallback } from "react";
import { usePlayerStore } from "@/stores/player";

const BACKEND_WS = "ws://127.0.0.1:8765/v1/audio/stream";
const PREFETCH = 3;
const SAMPLE_RATE = 24000;

export function useAudioStream(onChapterEnded?: () => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const gainNodeRef = useRef<GainNode | null>(null);
  const nextPlayTimeRef = useRef<number>(0);
  const sentQueueRef = useRef<number[]>([]);   // 紀錄已送出待合成的句子 index 佇列
  const activeSourcesRef = useRef<AudioBufferSourceNode[]>([]); // 紀錄目前正在播放的音訊源節點
  const hasSentLastSentenceRef = useRef<boolean>(false);
  
  // 實體音訊高亮同步與手動跳轉控制 refs
  const highlightTimeoutIdsRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const lastScheduledIndexRef = useRef<number | null>(null);
  const currentReceivingIndexRef = useRef<number | null>(null);
  const isAutoTickingRef = useRef<boolean>(false);

  const {
    isPlaying,
    sentences,
    currentSentenceIndex,
    speed,
    voice,
    ttsMode,
    refAudioPath,
    refText,
    instruct,
    numStep,
    duration,
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
    gainNode.gain.value = 0.8; // 預設 80% 音量
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

    // 清理高亮排程與狀態
    highlightTimeoutIdsRef.current.forEach(clearTimeout);
    highlightTimeoutIdsRef.current = [];
    lastScheduledIndexRef.current = null;
  }, []);

  // 發送句子給後端進行語音合成（攜帶完整語音模式設定）
  const sendSentence = useCallback((ws: WebSocket, index: number) => {
    if (index >= sentences.length) return;
    if (ws.readyState !== WebSocket.OPEN) return;

    // 根據語音模式決定要傳遞的參數
    const payload: Record<string, unknown> = {
      text: sentences[index].text,
      sentence_index: index,
      speed,
      num_step: numStep,
    };

    if (ttsMode === "clone" && refAudioPath) {
      payload.ref_audio_path = refAudioPath;
      if (refText) payload.ref_text = refText;
    } else if (ttsMode === "design" && instruct) {
      payload.instruct = instruct;
    }

    if (duration !== null) {
      payload.duration = duration;
    }

    ws.send(JSON.stringify(payload));
    sentQueueRef.current.push(index);
  }, [sentences, speed, ttsMode, refAudioPath, refText, instruct, numStep, duration]);

  // 處理文字訊息同步（sentence_start/end）
  const handleTextMessage = useCallback((msg: any, ws: WebSocket) => {
    if (msg.type === "sentence_start") {
      // 記錄當前正在接收 PCM 的句子索引，但不直接更新高亮（等 PCM 播放時才更新）
      currentReceivingIndexRef.current = msg.index;
    }
    if (msg.type === "sentence_end") {
      if (msg.index === sentences.length - 1) {
        hasSentLastSentenceRef.current = true;
      }
      // 獲取目前發送隊列中的最後一個句子索引，並發送其後下一句，維持快取緩衝
      const lastSent = sentQueueRef.current[sentQueueRef.current.length - 1] ?? msg.index;
      if (lastSent + 1 < sentences.length) {
        sendSentence(ws, lastSent + 1);
      }
    }
  }, [sentences, sendSentence]);

  // 處理收到的 PCM 音訊二進位資料並排程播放
  const handlePCMChunk = useCallback(async (buffer: ArrayBuffer, sentenceIndex: number) => {
    const ctx = audioCtxRef.current;
    if (!ctx) return;

    // 當開始播放 PCM 時，確保 loading 結束
    setIsLoading(false);

    if (ctx.state === "suspended") {
      await ctx.resume();
    }

    const int16 = new Int16Array(buffer);
    const float32 = new Float32Array(int16.length);

    // 將 PCM 16-bit 轉成 Web Audio API 需要的 float32 (-1.0 ~ 1.0)
    for (let i = 0; i < int16.length; i++) {
      float32[i] = int16[i] / 32768.0;
    }

    const audioBuffer = ctx.createBuffer(1, float32.length, SAMPLE_RATE);
    audioBuffer.copyToChannel(float32, 0);

    const source = ctx.createBufferSource();
    source.buffer = audioBuffer;
    
    // 連接至實體 GainNode 以實現音量調節，若無則降級連接至預設 destination
    if (gainNodeRef.current) {
      source.connect(gainNodeRef.current);
    } else {
      source.connect(ctx.destination);
    }

    // 紀錄此節點以便在暫停時能立即中斷
    activeSourcesRef.current.push(source);
    source.onended = () => {
      activeSourcesRef.current = activeSourcesRef.current.filter((s) => s !== source);
      // 若最後一句發送完成，且所有音軌都播完了，則觸發章節結束回調
      if (hasSentLastSentenceRef.current && activeSourcesRef.current.length === 0) {
        hasSentLastSentenceRef.current = false;
        onChapterEnded?.();
      }
    };

    // 無縫接續播放：若 nextPlayTime 小於當前時間，則立刻開始播放
    const startTime = Math.max(nextPlayTimeRef.current, ctx.currentTime);
    source.start(startTime);
    nextPlayTimeRef.current = startTime + audioBuffer.duration;

    // 排程實體播放時的高亮更新
    if (sentenceIndex !== null && sentenceIndex !== lastScheduledIndexRef.current) {
      lastScheduledIndexRef.current = sentenceIndex;
      const delayMs = Math.max(0, (startTime - ctx.currentTime) * 1000);
      const timeoutId = setTimeout(() => {
        isAutoTickingRef.current = true;
        _setCurrentIndex(sentenceIndex);
      }, delayMs);
      highlightTimeoutIdsRef.current.push(timeoutId);
    }
  }, [onChapterEnded, _setCurrentIndex]);

  const connectAndPlay = useCallback(() => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    // 清空舊的排程資訊
    stopAllAudio();
    sentQueueRef.current = [];
    hasSentLastSentenceRef.current = false;
    
    // 開始建立連線與語音合成，進入 loading 狀態
    setIsLoading(true);

    const ws = new WebSocket(BACKEND_WS);
    ws.binaryType = "arraybuffer"; // 設定直接返回 ArrayBuffer
    wsRef.current = ws;
    setWs(ws);

    if (audioCtxRef.current) {
      nextPlayTimeRef.current = audioCtxRef.current.currentTime;
    }

    ws.onopen = () => {
      // 建立連線後，一口氣送出當前句以及預取緩衝句
      const startIdx = currentSentenceIndex;
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
        // 二進位影格，此時 event.data 直接是 ArrayBuffer
        // 同步綁定當前正在接收的句子索引，防止被後續非同步訊息覆蓋
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
  }, [currentSentenceIndex, sentences, sendSentence, handleTextMessage, handlePCMChunk, stopAllAudio, setWs]);

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

    // 若不是自動更新，說明是使用者手動點選了其他句子
    console.log("[useAudioStream] 偵測到使用者手動跳轉至句子:", currentSentenceIndex);
    
    if (wsRef.current) {
      try {
        wsRef.current.close();
      } catch (e) {}
      wsRef.current = null;
    }
    stopAllAudio();
    connectAndPlay();
  }, [currentSentenceIndex, isPlaying, connectAndPlay, stopAllAudio]);

  return {
    resumeAudio,
    changeVolume,
  };
}

