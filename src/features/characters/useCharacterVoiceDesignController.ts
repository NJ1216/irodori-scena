import { useRef, useState } from "react";
import { api } from "../../api";
import type { Character, VoiceDesignEmotion } from "../../types";
import type { CharactersViewModelProps } from "./charactersViewModelTypes";
import { importBaselineReference, insertTextAtSelection, resetNewVoiceDesignIdentity } from "./characterViewModelHelpers";
import { useVoiceDesignFlow } from "./useVoiceDesignFlow";
import { normalizeVoiceDesign, type VoiceDesign } from "./voiceDesign";
import { generateBaseline, initializeVoiceDesignForm, insertVoiceSampleEmoji, mergeVoiceDesignSuggestion, useVoiceDesignFormState } from "./voiceDesignFormState";
import type { VoiceDesignSuggestedField } from "./VoiceDesignForm";
import { isMeanFlowSelection } from "../shared/ttsSampling";

type Params = Pick<CharactersViewModelProps, "project" | "connection" | "busy" | "onGenerateCandidates" | "onSaveVoiceDesign" | "onImportVoiceDesignReference" | "onClearCandidates" | "onNotice" | "onBusy">;

function runtimeCfgSettings(supported: boolean, textCfg: number, voiceCfg: number, captionCfg: number) {
  return supported ? { textCfg, voiceCfg, captionCfg } : {};
}

export function useCharacterVoiceDesignController(params: Params) {
  const form = useVoiceDesignFormState();
  const [sampleText, setSampleText] = useState("こんにちは。私はあなたの物語に寄り添うために、ここにいます。");
  const voiceDesign = useVoiceDesignFlow(params);
  const [count, setCount] = useState(3);
  const [baselineSpeechRate, setBaselineSpeechRate] = useState(1);
  const [voiceDesignTextCfg, setVoiceDesignTextCfg] = useState(params.project.settings.textCfg);
  const [voiceDesignVoiceCfg, setVoiceDesignVoiceCfg] = useState(params.project.settings.voiceCfg);
  const [voiceDesignCaptionCfg, setVoiceDesignCaptionCfg] = useState(3);
  const [name, setName] = useState("新規キャスト");
  const [profile, setProfile] = useState("");
  const [voiceSuggestionOpen, setVoiceSuggestionOpen] = useState(false);
  const [voiceDesignOpen, setVoiceDesignOpen] = useState(false);
  const [referenceVoiceTarget, setReferenceVoiceTarget] = useState<Character | null>(null);
  const [sourceKeywords, setSourceKeywords] = useState("");
  const sampleTextInput = useRef<HTMLTextAreaElement>(null);
  const supportsRuntimeCfg = !isMeanFlowSelection(params.project.ttsSelection);
  const generate = () => generateBaseline(form.voiceDesignValue, sampleText, count, { speechRate: baselineSpeechRate, ...runtimeCfgSettings(supportsRuntimeCfg, voiceDesignTextCfg, voiceDesignVoiceCfg, voiceDesignCaptionCfg) }, params.onGenerateCandidates, params.onNotice);
  const importVoiceDesignReference = (file: File) => importBaselineReference(file, params.onImportVoiceDesignReference, (id) => (voiceDesign.setBaselineCandidateId(id), voiceDesign.setEmotionCandidateIds({})));
  const importEmotionVoiceDesignReference = async (file: File, emotion: VoiceDesignEmotion) => {
    if (!voiceDesign.baselineCandidateId) return void params.onNotice("先に基準ボイスを選んでください。");
    const candidate = await params.onImportVoiceDesignReference(file, { kind: "emotion", emotion, referenceCandidateId: voiceDesign.baselineCandidateId });
    if (candidate) voiceDesign.setEmotionCandidateIds((current) => ({ ...current, [emotion]: candidate.id }));
  };
  const setIncludeEmotions = (include: boolean) => {
    voiceDesign.setIncludeEmotions(include);
    if (!include) voiceDesign.setEmotionCandidateIds({});
  };
  const openVoiceDesign = () => {
    resetNewVoiceDesignIdentity(setReferenceVoiceTarget, setName);
    initializeVoiceDesignForm(null, setReferenceVoiceTarget, form.setVoiceDesignValue, setSourceKeywords, form.setVoiceDesignSuggestedFields, form.setSampleTextSuggested);
    voiceDesign.resetVoiceDesignSession();
    setVoiceDesignOpen(true);
  };
  const closeVoiceDesign = () => (setVoiceDesignOpen(false), setReferenceVoiceTarget(null));
  const clearVoiceDesignCandidates = async () => (await params.onClearCandidates(), voiceDesign.resetVoiceDesignSession());
  async function suggestVoiceDesign(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!sourceKeywords.trim()) return void params.onNotice("元になるキーワードを入力してください。");
    if (!params.connection.model.trim()) return void params.onNotice("設定ページで既定のLLMモデルを選択してください。");
    params.onBusy("voice-design-suggestion");
    try {
      const result = await api.suggestVoiceDesign({
        keywords: sourceKeywords,
        character_context: referenceVoiceTarget ? JSON.stringify({ name: referenceVoiceTarget.name, profile: referenceVoiceTarget.profile, details: referenceVoiceTarget.profileDetails ?? {}, voiceKeywords: referenceVoiceTarget.voiceKeywords }) : "",
      });
      const proposal = normalizeVoiceDesign(result.voiceDesign);
      const { next, applied } = mergeVoiceDesignSuggestion(form.voiceDesignValue, proposal);
      form.setVoiceDesignValue(next);
      form.setVoiceDesignSuggestedFields((current) => new Set([...current, ...applied]));
      if (result.baselineText) {
        setSampleText(result.baselineText);
        form.setSampleTextSuggested(true);
      }
      voiceDesign.setEmotionTexts((current) => ({ ...current, ...result.emotionTexts }));
      voiceDesign.setSuggestedEmotionTexts(new Set(Object.keys(result.emotionTexts) as VoiceDesignEmotion[]));
      setVoiceSuggestionOpen(false);
      params.onNotice("AIの声設計と試聴台詞を反映しました。必要なら編集して候補を生成してください。");
    } catch (error) {
      params.onNotice(`AIに声の設計を相談できませんでした: ${(error as Error).message}`);
    } finally {
      params.onBusy(null);
    }
  }
  const beginReferenceVoiceDesign = (character: Character) => {
    initializeVoiceDesignForm(character, setReferenceVoiceTarget, form.setVoiceDesignValue, setSourceKeywords, form.setVoiceDesignSuggestedFields, form.setSampleTextSuggested, setSampleText);
    voiceDesign.resetVoiceDesignSession();
    setVoiceDesignOpen(true);
  };
  const setVoiceDesignValue = (value: VoiceDesign, field?: VoiceDesignSuggestedField) => {
    form.setVoiceDesignValue(value);
    if (field)
      form.setVoiceDesignSuggestedFields((current) => {
        const next = new Set(current);
        next.delete(field);
        return next;
      });
  };
  return {
    ...form,
    setVoiceDesignValue,
    sampleText,
    setSampleText,
    ...voiceDesign,
    setIncludeEmotions,
    openVoiceDesign,
    closeVoiceDesign,
    clearVoiceDesignCandidates,
    count,
    setCount,
    baselineSpeechRate,
    setBaselineSpeechRate,
    voiceDesignTextCfg,
    setVoiceDesignTextCfg,
    voiceDesignVoiceCfg,
    setVoiceDesignVoiceCfg,
    voiceDesignCaptionCfg,
    setVoiceDesignCaptionCfg,
    supportsRuntimeCfg,
    name,
    setName,
    profile,
    setProfile,
    voiceSuggestionOpen,
    setVoiceSuggestionOpen,
    voiceDesignOpen,
    referenceVoiceTarget,
    setReferenceVoiceTarget,
    sourceKeywords,
    setSourceKeywords,
    sampleTextInput,
    suggestingVoice: params.busy === "voice-design-suggestion",
    insertSampleTextEmoji: (emoji: string) => insertVoiceSampleEmoji(sampleTextInput.current, emoji, setSampleText, form.setSampleTextSuggested, insertTextAtSelection),
    generate,
    importVoiceDesignReference,
    importEmotionVoiceDesignReference,
    suggestVoiceDesign,
    beginReferenceVoiceDesign,
  };
}
