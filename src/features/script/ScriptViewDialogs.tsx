import { CastSwitchDialog } from "./CastSwitchDialog";
import { ScriptCastContextDialog } from "./ScriptCastContextDialog";
import type { ScriptViewProps } from "./ScriptViewTypes";

export function ScriptViewDialogs({ props, castSwitchOpen, editingCastId, onCloseCastSwitch, onCloseCastContext }: { props: ScriptViewProps; castSwitchOpen: boolean; editingCastId: string | null; onCloseCastSwitch: () => void; onCloseCastContext: () => void }) {
  const character = editingCastId ? props.project.characters.find((item) => item.id === editingCastId) : undefined;
  return (
    <>
      {castSwitchOpen && (
        <CastSwitchDialog
          project={props.project}
          busy={props.busy === "switch-characters"}
          onClose={onCloseCastSwitch}
          onApply={async (mappings) => {
            await props.onSwitchCharacters(mappings);
            onCloseCastSwitch();
          }}
        />
      )}
      {character && <ScriptCastContextDialog character={character} context={props.project.scriptCastContexts?.[character.id]} onClose={onCloseCastContext} onSave={(context) => props.onUpdateCastContext(character.id, context)} />}
    </>
  );
}
