import { api } from "../../api";
import type { VoiceDesignEmotion } from "../../types";
import type { VoiceDesign } from "../characters/voiceDesign";
import { importDesignedReference, saveDesignedReference } from "./referenceVoiceActions";
import type { CharacterActionModel } from "./studioCharacterActionTypes";

export function useVoiceCandidateActions(model: CharacterActionModel) {
  const { editSession, setBusy, setNotice, stop } = model;
  async function generateCandidates(keywords: string, count: number, sampleText: string, options?: { kind: "baseline" | "emotion"; emotion?: VoiceDesignEmotion; referenceCandidateId?: string; speechRate?: number; textCfg?: number; voiceCfg?: number; captionCfg?: number; voiceDesign?: VoiceDesign }) {
    setBusy("candidates");
    setNotice("VoiceDesign候補を生成しています。最初の生成は少し時間がかかります。");
    try {
      const result = await editSession.requestUpdate(
        () => api.candidates(keywords, count, sampleText, options),
        (current, result) => ({ ...current, candidates: [...current.candidates, ...result.candidates] }),
      );
      if (!result) return false;
      setNotice(`${result.candidates.length} 件の声候補を追加しました。採用しない候補はページを離れると消去されます。`);
      return true;
    } catch (error) {
      setNotice(`候補を作れませんでした: ${(error as Error).message}`);
      return false;
    } finally {
      setBusy(null);
    }
  }
  const importVoiceDesignReference = (file: File, options?: { kind: "baseline" | "emotion"; emotion?: VoiceDesignEmotion; referenceCandidateId?: string }) => importDesignedReference({ stop, setBusy, editSession, setNotice }, file, options);
  const saveVoiceDesign = (payload: Parameters<typeof api.saveVoiceDesign>[0]) => saveDesignedReference({ stop, setBusy, editSession, setNotice }, payload);
  return { generateCandidates, importVoiceDesignReference, saveVoiceDesign };
}
