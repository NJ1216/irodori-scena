import { useState } from "react";
import type { Character, VoiceDesignEmotion } from "../../types";
import type { CharactersViewModelProps } from "./charactersViewModelTypes";
import type { VoiceDesignSuggestedField } from "./VoiceDesignForm";
import { emptyVoiceDesign, hasVoiceDesignInput, normalizeVoiceDesign, voiceDesignKeywords, type VoiceDesign } from "./voiceDesign";

/** The first failed baseline check and the field it belongs to; no field means the check spans the whole voice form. */
export const baselineInputError = (design: VoiceDesign, sampleText: string): { message: string; field?: "sampleText" | "notes" } | null =>
  !hasVoiceDesignInput(design) ? { message: "声の条件を1項目以上入力してください。" } : !sampleText.trim() ? { message: "候補を聞き比べるサンプル台詞を入力してください。", field: "sampleText" } : design.notes.length > 600 ? { message: "追加要望・備考は600文字以内で入力してください。", field: "notes" } : null;
export function mergeVoiceDesignSuggestion(current: VoiceDesign, proposal: VoiceDesign) {
  const next = { ...current };
  const applied = new Set<VoiceDesignSuggestedField>();
  for (const key of ["age", "gender", "pitch", "style"] as const)
    if (!current[key] && proposal[key]) {
      next[key] = proposal[key];
      applied.add(key);
    }
  if (!current.qualities.length && proposal.qualities.length) {
    next.qualities = proposal.qualities;
    applied.add("qualities");
  }
  if (!current.notes.trim() && proposal.notes.trim()) {
    next.notes = proposal.notes;
    applied.add("notes");
  }
  return { next, applied };
}
export const voiceSuggestionInputError = (keywords: string, model: string): { message: string; field?: "sourceKeywords" } | null => (!keywords.trim() ? { message: "元になるキーワードを入力してください。", field: "sourceKeywords" } : !model.trim() ? { message: "設定ページで既定のLLMモデルを選択してください。" } : null);
type VoiceDesignSuggestionResult = { voiceDesign?: Parameters<typeof normalizeVoiceDesign>[0]; baselineText?: string | null; emotionTexts: Partial<Record<VoiceDesignEmotion, string>> };
/** Fills only empty voice fields from the AI proposal and replaces the audition lines it returned. */
export function applyVoiceDesignSuggestion(
  result: VoiceDesignSuggestionResult,
  form: ReturnType<typeof useVoiceDesignFormState>,
  setSampleText: (value: string) => void,
  flow: { setEmotionTexts: React.Dispatch<React.SetStateAction<Record<VoiceDesignEmotion, string>>>; setSuggestedEmotionTexts: (value: Set<VoiceDesignEmotion>) => void },
) {
  const { next, applied } = mergeVoiceDesignSuggestion(form.voiceDesignValue, normalizeVoiceDesign(result.voiceDesign));
  form.setVoiceDesignValue(next);
  form.setVoiceDesignSuggestedFields((current) => new Set([...current, ...applied]));
  if (result.baselineText) {
    setSampleText(result.baselineText);
    form.setSampleTextSuggested(true);
  }
  flow.setEmotionTexts((current) => ({ ...current, ...result.emotionTexts }));
  flow.setSuggestedEmotionTexts(new Set(Object.keys(result.emotionTexts) as VoiceDesignEmotion[]));
}
export function initializeVoiceDesignForm(
  character: Character | null,
  setTarget: (value: Character | null) => void,
  setDesign: (value: VoiceDesign) => void,
  setSource: (value: string) => void,
  setSuggested: (value: Set<VoiceDesignSuggestedField>) => void,
  setSampleSuggested: (value: boolean) => void,
  setSampleText?: (value: string) => void,
) {
  if (character) setSampleText?.(character.sampleText?.trim() || "こんにちは。私はあなたの物語に寄り添うために、ここにいます。");
  setTarget(character);
  setDesign(character?.voiceDesign ? normalizeVoiceDesign(character.voiceDesign) : { ...emptyVoiceDesign(), notes: character?.voiceKeywords ?? "" });
  setSource(character?.voiceKeywords ?? "");
  setSuggested(new Set());
  setSampleSuggested(false);
}
export function useVoiceDesignFormState() {
  const [voiceDesignValue, setVoiceDesignValue] = useState<VoiceDesign>(emptyVoiceDesign);
  const [voiceDesignSuggestedFields, setVoiceDesignSuggestedFields] = useState<Set<VoiceDesignSuggestedField>>(new Set());
  const [sampleTextSuggested, setSampleTextSuggested] = useState(false);
  const keywords = voiceDesignKeywords(voiceDesignValue);
  const setKeywords = (value: string) => setVoiceDesignValue({ ...emptyVoiceDesign(), notes: value });
  return { voiceDesignValue, setVoiceDesignValue, voiceDesignSuggestedFields, setVoiceDesignSuggestedFields, sampleTextSuggested, setSampleTextSuggested, keywords, setKeywords };
}
export async function generateBaseline(design: VoiceDesign, sampleText: string, count: number, settings: { speechRate: number; textCfg?: number; voiceCfg?: number; captionCfg?: number }, generate: CharactersViewModelProps["onGenerateCandidates"], report: (message: string, field?: string) => void) {
  const inputError = baselineInputError(design, sampleText);
  if (inputError) {
    report(inputError.message, inputError.field);
    return false;
  }
  return generate(voiceDesignKeywords(design), count, sampleText, { kind: "baseline", voiceDesign: design, ...settings });
}
export function insertVoiceSampleEmoji(input: HTMLTextAreaElement | null, emoji: string, setText: (value: string) => void, setSuggested: (value: boolean) => void, insert: (input: HTMLTextAreaElement | null, value: string, setter: (value: string) => void) => void) {
  insert(input, emoji, setText);
  setSuggested(false);
}
