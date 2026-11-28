import { useState } from "react";
import type { VoiceDesignEmotion } from "../../types";
import type { VoiceDesign } from "./voiceDesign";
import { reportCharacterMemoLimit } from "./characterMemo";

const initialEmotionTexts: Record<VoiceDesignEmotion, string> = {
  normal: "今日は穏やかに話せて、うれしいです。",
  joy: "わあ、😆本当に😊うれしいです！",
  anger: "もう、😠本当に💥見過ごせません。",
  sorrow: "🥺少しだけ、😭寂しくなりました。",
  delight: "やった、😆😊素敵な時間ですね。",
};
const emotionKeys: VoiceDesignEmotion[] = ["normal", "joy", "anger", "sorrow", "delight"];

export function useVoiceDesignFlow({
  onGenerateCandidates,
  onSaveVoiceDesign,
  onInvalid,
}: {
  onGenerateCandidates: (
    keywords: string,
    count: number,
    text: string,
    options: {
      kind: "emotion";
      emotion: VoiceDesignEmotion;
      referenceCandidateId: string;
      speechRate: number;
      textCfg?: number;
      voiceCfg?: number;
      captionCfg?: number;
      voiceDesign?: VoiceDesign;
    },
  ) => Promise<boolean>;
  onSaveVoiceDesign: (payload: { baselineCandidateId: string; emotionCandidateIds: Partial<Record<VoiceDesignEmotion, string>>; name: string; profile: string; voiceKeywords: string; voiceDesign: VoiceDesign; characterId?: string }) => Promise<boolean>;
  /** Reports a failed input check inline in the dialog; a field names the control at fault. */
  onInvalid: (message: string, field?: string) => void;
}) {
  const [emotionTexts, setEmotionTexts] = useState(initialEmotionTexts);
  const [suggestedEmotionTexts, setSuggestedEmotionTexts] = useState<Set<VoiceDesignEmotion>>(new Set());
  const [baselineCandidateId, setBaselineCandidateId] = useState<string | null>(null);
  const [emotionCandidateIds, setEmotionCandidateIds] = useState<Partial<Record<VoiceDesignEmotion, string>>>({});
  const [includeEmotions, setIncludeEmotions] = useState(false);
  function resetVoiceDesignSession() {
    setBaselineCandidateId(null);
    setEmotionCandidateIds({});
    setIncludeEmotions(false);
    setSuggestedEmotionTexts(new Set());
  }
  async function generateEmotion(emotion: VoiceDesignEmotion, keywords: string, voiceDesign: VoiceDesign, count: number, settings: { speechRate: number; textCfg?: number; voiceCfg?: number; captionCfg?: number }) {
    if (!baselineCandidateId) return onInvalid("先に基準ボイスを選んでください。");
    if (!emotionTexts[emotion].trim()) return onInvalid("感情用の台詞を入力してください。", `emotion-${emotion}`);
    await onGenerateCandidates(keywords, count, emotionTexts[emotion], {
      kind: "emotion",
      emotion,
      referenceCandidateId: baselineCandidateId,
      voiceDesign,
      ...settings,
    });
  }
  const hasSelectedEmotion = emotionKeys.some((emotion) => Boolean(emotionCandidateIds[emotion]));
  const canSaveVoiceDesign = Boolean(baselineCandidateId) && (!includeEmotions || emotionKeys.every((emotion) => Boolean(emotionCandidateIds[emotion])));
  const canReplaceVoiceDesign = Boolean(baselineCandidateId) && (!includeEmotions || hasSelectedEmotion);
  async function saveDesignedVoice(values: { name: string; profile: string; voiceKeywords: string; voiceDesign: VoiceDesign; characterId?: string }) {
    if (!values.characterId && !values.name.trim()) {
      onInvalid("キャスト名は必須です。", "castName");
      return false;
    }
    if (reportCharacterMemoLimit(values.profile, onInvalid, "profile")) return false;
    const canCommit = values.characterId ? canReplaceVoiceDesign : canSaveVoiceDesign;
    if (!baselineCandidateId || !canCommit) {
      onInvalid(values.characterId ? "感情参照を追加する場合は、感情クリップを1つ以上選んでください。" : "感情を追加する場合は、5種類すべての感情クリップを選んでください。");
      return false;
    }
    return onSaveVoiceDesign({
      baselineCandidateId,
      emotionCandidateIds: includeEmotions ? emotionCandidateIds : {},
      ...values,
    });
  }
  return {
    emotionTexts,
    setEmotionTexts,
    suggestedEmotionTexts,
    setSuggestedEmotionTexts,
    baselineCandidateId,
    setBaselineCandidateId,
    emotionCandidateIds,
    setEmotionCandidateIds,
    includeEmotions,
    setIncludeEmotions,
    resetVoiceDesignSession,
    generateEmotion,
    saveDesignedVoice,
    canSaveVoiceDesign,
    canReplaceVoiceDesign,
  };
}
