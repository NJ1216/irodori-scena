import { useState } from "react";
import { api } from "../../api";
import type { Character, CharacterProfile, ImagePromptPreferences, LlmConnection } from "../../types";
import { emptyImagePromptDraft, imagePromptDraftFromPreferences, imagePromptPreferencesFromDraft, imagePromptRequestFromDraft, type ImagePromptDraft } from "./imagePromptDraft";
import { imagePromptDraftBindings } from "./imagePromptDraftBindings";

export function useCharacterImagePromptSuggestion({
  busy,
  onBusy,
  editing,
  onPromptReady,
}: {
  connection: LlmConnection;
  busy: string | null;
  onBusy: (value: string | null) => void;
  editing: Character | null;
  name: string;
  profile: string;
  profileDetails: () => CharacterProfile;
  onPromptReady: (imagePrompt: string, preferences: ImagePromptPreferences) => Promise<boolean>;
}) {
  const [editImagePrompt, setEditImagePrompt] = useState("");
  const [imagePromptSuggestionOpen, setImagePromptSuggestionOpen] = useState(false);
  const [imagePromptDraft, setImagePromptDraft] = useState(emptyImagePromptDraft);
  const [imagePromptSuggestionError, setImagePromptSuggestionError] = useState("");
  const suggestingImagePrompt = busy === "character-image-prompt-suggestion";
  function updateImagePromptField<K extends keyof ImagePromptDraft>(field: K, value: ImagePromptDraft[K]) {
    setImagePromptDraft((current) => ({ ...current, [field]: value }));
  }
  function loadCharacterImagePrompt(character: Character) {
    setEditImagePrompt(character.imagePrompt ?? "");
    setImagePromptSuggestionOpen(false);
    setImagePromptSuggestionError("");
    setImagePromptDraft(imagePromptDraftFromPreferences(character.imagePromptPreferences));
  }
  function imagePromptPreferences() {
    return imagePromptPreferencesFromDraft(imagePromptDraft);
  }
  async function suggestCharacterImagePrompt(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!editing) return;
    setImagePromptSuggestionError("");
    onBusy("character-image-prompt-suggestion");
    try {
      const result = await api.suggestCharacterImagePrompt(imagePromptRequestFromDraft(imagePromptDraft));
      if (!(await onPromptReady(result.imagePrompt, imagePromptPreferences()))) return;
      setEditImagePrompt(result.imagePrompt);
      if (result.warnings?.length) setImagePromptSuggestionError(result.warnings.join("\n"));
      else setImagePromptSuggestionOpen(false);
    } catch (error) {
      setImagePromptSuggestionError(`画像用プロンプトを作成できませんでした: ${(error as Error).message}`);
    } finally {
      onBusy(null);
    }
  }
  return {
    editImagePrompt,
    setEditImagePrompt,
    imagePromptSuggestionOpen,
    setImagePromptSuggestionOpen,
    imagePromptDraft,
    updateImagePromptField,
    imagePromptSuggestionError,
    setImagePromptSuggestionError,
    suggestingImagePrompt,
    loadCharacterImagePrompt,
    imagePromptPreferences,
    suggestCharacterImagePrompt,
    ...imagePromptDraftBindings(imagePromptDraft, updateImagePromptField),
  };
}
