import { AvatarCropDialog } from "./AvatarCropDialog";
import { CharacterEditDialog } from "./CharacterEditDialog";
import { CharacterProfileSuggestionDialog } from "./CharacterProfileSuggestionDialog";
import { CharacterImagePromptSuggestionDialog } from "./CharacterImagePromptSuggestionDialog";
import { CharactersOverview } from "./CharactersOverview";
import { CharacterVoiceDialogs } from "./CharacterVoiceDialogs";
import { type CharactersViewProps, useCharactersViewModel } from "./useCharactersViewModel";

export function CharactersView({ active, onImportCasts, ...props }: CharactersViewProps & { active: boolean; onImportCasts: () => void }) {
  const model = useCharactersViewModel(props);
  const { avatarSource, editing, setAvatarSource, setEditAvatarChange } = model;
  return (
    <section className="page characters-page" hidden={!active}>
      <CharactersOverview key={model.project.id} model={model} onImportCasts={onImportCasts} />
      <CharacterVoiceDialogs model={model} />
      <CharacterEditDialog model={model} />
      <CharacterProfileSuggestionDialog model={model} />
      <CharacterImagePromptSuggestionDialog model={model} />
      {avatarSource && editing && (
        <AvatarCropDialog
          source={avatarSource}
          saving={false}
          onClose={() => setAvatarSource(null)}
          onSave={(original, thumbnail) => {
            setEditAvatarChange({ original, thumbnail });
            setAvatarSource(null);
          }}
        />
      )}
    </section>
  );
}
