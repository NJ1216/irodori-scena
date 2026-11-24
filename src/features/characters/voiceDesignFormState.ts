import { useState } from "react";
import type { Character } from "../../types";
import type { CharactersViewModelProps } from "./charactersViewModelTypes";
import type { VoiceDesignSuggestedField } from "./VoiceDesignForm";
import { emptyVoiceDesign, hasVoiceDesignInput, normalizeVoiceDesign, voiceDesignKeywords, type VoiceDesign } from "./voiceDesign";

export const baselineInputError = (design: VoiceDesign, sampleText: string) => (!hasVoiceDesignInput(design) ? "声の条件を1項目以上入力してください。" : !sampleText.trim() ? "候補を聞き比べるサンプル台詞を入力してください。" : design.notes.length > 600 ? "追加要望・備考は600文字以内で入力してください。" : "");
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
export async function generateBaseline(design: VoiceDesign, sampleText: string, count: number, settings: { speechRate: number; textCfg?: number; voiceCfg?: number; captionCfg?: number }, generate: CharactersViewModelProps["onGenerateCandidates"], notice: (value: string) => void) {
  const inputError = baselineInputError(design, sampleText);
  if (inputError) {
    notice(inputError);
    return false;
  }
  return generate(voiceDesignKeywords(design), count, sampleText, { kind: "baseline", voiceDesign: design, ...settings });
}
export function insertVoiceSampleEmoji(input: HTMLTextAreaElement | null, emoji: string, setText: (value: string) => void, setSuggested: (value: boolean) => void, insert: (input: HTMLTextAreaElement | null, value: string, setter: (value: string) => void) => void) {
  insert(input, emoji, setText);
  setSuggested(false);
}
