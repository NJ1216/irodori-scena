import type { CharacterActionModel } from "./studioCharacterActionTypes";
import { useCharacterPersistenceActions } from "./useCharacterPersistenceActions";
import { useProjectMaintenanceActions } from "./useProjectMaintenanceActions";
import { useScriptDeletionActions } from "./useScriptDeletionActions";
import { useVoiceCandidateActions } from "./useVoiceCandidateActions";

export function useStudioCharacterActions(model: CharacterActionModel) {
  return {
    ...useCharacterPersistenceActions(model),
    ...useScriptDeletionActions(model),
    ...useProjectMaintenanceActions(model),
    ...useVoiceCandidateActions(model),
  };
}

export type StudioCharacterActions = ReturnType<typeof useStudioCharacterActions>;
