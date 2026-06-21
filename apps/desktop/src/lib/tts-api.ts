import { BACKEND_BASE_URL } from "./constants";

const BASE = `${BACKEND_BASE_URL}/v1/audio`;

export interface TTSSettings {
  forced_language: string | null;
  voice_consistency: boolean;
}

/** 取得 TTS 全域設定。 */
export async function getTTSSettings(): Promise<TTSSettings> {
  const r = await fetch(`${BASE}/settings`);
  if (!r.ok) throw new Error(`getTTSSettings ${r.status}`);
  return r.json();
}

/** 更新 TTS 全域設定（部分欄位）。 */
export async function patchTTSSettings(patch: Partial<TTSSettings>): Promise<TTSSettings> {
  const r = await fetch(`${BASE}/settings`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error(`patchTTSSettings ${r.status}`);
  return r.json();
}

/** 清除自我錨定的旁白/對白聲線，下次合成重新取聲。 */
export async function resetVoiceAnchors(): Promise<void> {
  const r = await fetch(`${BASE}/voice/reset`, { method: "POST" });
  if (!r.ok) throw new Error(`resetVoiceAnchors ${r.status}`);
}
