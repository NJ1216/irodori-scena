import { useRef, useState } from "react";
import { api } from "../../api";
import type { Character, VoiceDesignEmotion } from "../../types";
import type { CharactersViewModelProps } from "./charactersViewModelTypes";
import { importBaselineReference, insertTextAtSelection, resetNewVoiceDesignIdentity } from "./characterViewModelHelpers";
import { useVoiceDesignFlow } from "./useVoiceDesignFlow";
import type { VoiceDesign } from "./voiceDesign";
import { applyVoiceDesignSuggestion, generateBaseline, initializeVoiceDesignForm, insertVoiceSampleEmoji, useVoiceDesignFormState, voiceSuggestionInputError } from "./voiceDesignFormState";
import type { VoiceDesignSuggestedField } from "./VoiceDesignForm";
import { isMeanFlowSelection } from "../shared/ttsSampling";
import { useInlineValidation } from "../shared/useInlineValidation";

type Params = Pick<CharactersViewModelProps, "project" | "connection" | "busy" | "onGenerateCandidates" | "onSaveVoiceDesign" | "onImportVoiceDesignReference" | "onClearCandidates" | "onNotice" | "onStatusNotice" | "onBusy">;

function runtimeCfgSettings(supported: boolean, textCfg: number, voiceCfg: number, captionCfg: number) {
  return supported ? { textCfg, voiceCfg, captionCfg } : {};
}

export function useCharacterVoiceDesignController(params: Params) {
  const form = useVoiceDesignFormState();
  const voiceDesignValidation = useInlineValidation();
  const voiceSuggestionValidation = useInlineValidation();
  const [sampleText, setSampleText] = useState("こんにちは。私はあなたの物語に寄り添うために、ここにいます。");
  const voiceDesign = useVoiceDesignFlow({ ...params, onInvalid: voiceDesignValidation.report });
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
  const generate = () => generateBaseline(form.voiceDesignValue, sampleText, count, { speechRate: baselineSpeechRate, ...runtimeCfgSettings(supportsRuntimeCfg, voiceDesignTextCfg, voiceDesignVoiceCfg, voiceDesignCaptionCfg) }, params.onGenerateCandidates, voiceDesignValidation.report);
  const importVoiceDesignReference = (file: File) => importBaselineReference(file, params.onImportVoiceDesignReference, (id) => (voiceDesign.setBaselineCandidateId(id), voiceDesign.setEmotionCandidateIds({})));
  const importEmotionVoiceDesignReference = async (file: File, emotion: VoiceDesignEmotion) => {
    if (!voiceDesign.baselineCandidateId) return void voiceDesignValidation.report("先に基準ボイスを選んでください。");
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
    voiceDesignValidation.clear();
    setVoiceDesignOpen(true);
  };
  const closeVoiceDesign = () => (setVoiceDesignOpen(false), setReferenceVoiceTarget(null), voiceDesignValidation.clear());
  const clearVoiceDesignCandidates = async () => (await params.onClearCandidates(), voiceDesign.resetVoiceDesignSession());
  async function suggestVoiceDesign(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const inputError = voiceSuggestionInputError(sourceKeywords, params.connection.model);
    if (inputError) return void voiceSuggestionValidation.report(inputError.message, inputError.field);
    voiceSuggestionValidation.clear();
    params.onBusy("voice-design-suggestion");
    try {
      const result = await api.suggestVoiceDesign({
        keywords: sourceKeywords,
        character_context: referenceVoiceTarget ? JSON.stringify({ name: referenceVoiceTarget.name, profile: referenceVoiceTarget.profile, details: referenceVoiceTarget.profileDetails ?? {}, voiceKeywords: referenceVoiceTarget.voiceKeywords }) : "",
      });
      applyVoiceDesignSuggestion(result, form, setSampleText, voiceDesign);
      setVoiceSuggestionOpen(false);
      params.onStatusNotice("AIの声設計と試聴台詞を反映しました。必要なら編集して候補を生成してください。");
    } catch (error) {
      params.onNotice(`AIに声の設計を相談できませんでした: ${(error as Error).message}`);
    } finally {
      params.onBusy(null);
    }
  }
  const beginReferenceVoiceDesign = (character: Character) => {
    initializeVoiceDesignForm(character, setReferenceVoiceTarget, form.setVoiceDesignValue, setSourceKeywords, form.setVoiceDesignSuggestedFields, form.setSampleTextSuggested, setSampleText);
    voiceDesign.resetVoiceDesignSession();
    voiceDesignValidation.clear();
    setVoiceDesignOpen(true);
  };
  const setVoiceDesignValue = (value: VoiceDesign, field?: VoiceDesignSuggestedField) => {
    form.setVoiceDesignValue(value);
    voiceDesignValidation.clearForm();
    if (field === "notes") voiceDesignValidation.clear("notes");
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
    setSampleText: (value: string) => (setSampleText(value), voiceDesignValidation.clear("sampleText")),
    ...voiceDesign,
    voiceDesignValidation,
    voiceSuggestionValidation,
    setVoiceSuggestionOpen: (open: boolean) => (setVoiceSuggestionOpen(open), voiceSuggestionValidation.clear()),
    setSourceKeywords: (value: string) => (setSourceKeywords(value), voiceSuggestionValidation.clear("sourceKeywords")),
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
    voiceDesignOpen,
    referenceVoiceTarget,
    setReferenceVoiceTarget,
    sourceKeywords,
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
