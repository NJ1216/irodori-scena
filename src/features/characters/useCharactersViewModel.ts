import { useCharacterAudioPlayback } from "./useCharacterAudioPlayback";
import { useCharacterEditor } from "./useCharacterEditor";
import { useCharacterImagePromptSuggestion } from "./useCharacterImagePromptSuggestion";
import { useCharacterImportForm } from "./useCharacterImportForm";
import { useCharacterProfileSuggestion } from "./useCharacterProfileSuggestion";
import { useCharacterVoiceDesignController } from "./useCharacterVoiceDesignController";
import type { CharactersViewModelProps } from "./charactersViewModelTypes";
import { useTtsCapabilityReasons } from "./useTtsCapabilityReasons";

export function useCharactersViewModel(props: CharactersViewModelProps) {
  const editor = useCharacterEditor(props.onNotice);
  const suggestion = useCharacterProfileSuggestion({
    project: props.project,
    connection: props.connection,
    busy: props.busy,
    editing: editor.editing,
    editName: editor.editName,
    editProfile: editor.editProfile,
    details: editor.editableProfileDetails,
    setEditName: editor.setEditName,
    setEditDetails: editor.setEditDetails,
    setEditAliases: editor.setEditAliases,
    setEditFirstPerson: editor.setEditFirstPerson,
    setEditSecondPerson: editor.setEditSecondPerson,
    onNotice: props.onNotice,
    onStatusNotice: props.onStatusNotice,
    onBusy: props.onBusy,
  });
  const imagePrompt = useCharacterImagePromptSuggestion({
    connection: props.connection,
    busy: props.busy,
    onBusy: props.onBusy,
    editing: editor.editing,
    name: editor.editName,
    profile: editor.editProfile,
    profileDetails: editor.editableProfileDetails,
    onPromptReady: async (prompt, preferences) => {
      const saved = props.project.characters.find((character) => character.id === editor.editing?.id);
      return saved ? props.onUpdate(saved, saved.name, saved.profile, saved.voiceKeywords, saved.profileDetails ?? {}, prompt, preferences) : false;
    },
  });
  const voice = useCharacterVoiceDesignController(props);
  const capabilityReasons = useTtsCapabilityReasons(props.project.ttsSelection);
  const playback = useCharacterAudioPlayback();
  const importForm = useCharacterImportForm(props.onImport);
  const beginEdit = (character: Parameters<typeof editor.beginEdit>[0]) =>
    editor.beginEdit(character, () => {
      suggestion.resetProfileSuggestion();
      imagePrompt.loadCharacterImagePrompt(character);
    });
  const beginReferenceVoiceDesign = (character: Parameters<typeof voice.beginReferenceVoiceDesign>[0]) => {
    editor.setEditing(null);
    voice.beginReferenceVoiceDesign(character);
  };
  const openVoiceDesign = () => {
    if (capabilityReasons.voiceDesignUnavailableReason) return void props.onNotice(capabilityReasons.voiceDesignUnavailableReason);
    voice.openVoiceDesign();
  };
  const saveEdit = (event: React.FormEvent<HTMLFormElement>) => editor.saveEdit(event, { imagePrompt: imagePrompt.editImagePrompt, preferences: imagePrompt.imagePromptPreferences(), onUpdate: props.onUpdate, onRemoveAvatar: props.onRemoveAvatar, onUpdateAvatar: props.onUpdateAvatar });
  return { ...props, ...voice, ...capabilityReasons, ...importForm, ...editor, ...suggestion, ...imagePrompt, ...playback, beginEdit, beginReferenceVoiceDesign, openVoiceDesign, saveEdit, suggestingProfile: props.busy === "character-profile-suggestion" };
}

export type CharactersViewProps = Parameters<typeof useCharactersViewModel>[0];
export type CharactersViewModel = ReturnType<typeof useCharactersViewModel>;
