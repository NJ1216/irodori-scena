import { useStudioAutoRender } from "./useStudioAutoRender";
import { useStudioCharacterActions } from "./useStudioCharacterActions";
import { useStudioEffects } from "./useStudioEffects";
import { useStudioJobActions } from "./useStudioJobActions";
import { useStudioLineActions } from "./useStudioLineActions";
import { useStudioPlayback } from "./useStudioPlayback";
import { useStudioProjectEditing } from "./useStudioProjectEditing";
import { useStudioState } from "./useStudioState";
import { useStudioPlaybackDisplay } from "./useStudioPlaybackDisplay";
import { useStudioHistory } from "./useStudioHistory";
import { useStudioShortcuts } from "./useStudioShortcuts";
import { useStudioSelectedLineActions } from "./useStudioSelectedLineActions";
import { useStudioScriptReplace } from "./useStudioScriptReplace";
import { useDictionaryRegeneration } from "./useDictionaryRegeneration";
import { useCastImport } from "./useCastImport";

export function useStudioController() {
  const state = useStudioState();
  const projectEditing = useStudioProjectEditing(state);
  const replaceLineTexts = useStudioScriptReplace({ ...state, ...projectEditing });
  const lineActions = useStudioLineActions({ ...state, ...projectEditing });
  const playback = useStudioPlayback({
    ...state,
    ...projectEditing,
    ...lineActions,
  });
  const characterActions = useStudioCharacterActions({
    ...state,
    ...projectEditing,
    ...lineActions,
    ...playback,
  });
  const autoRender = useStudioAutoRender({
    ...state,
    ...lineActions,
    ...playback,
  });
  const jobActions = useStudioJobActions({
    ...state,
    ...projectEditing,
    ...lineActions,
    ...playback,
    ...characterActions,
    ...autoRender,
  });
  const history = useStudioHistory(state);
  const selectedLineActions = useStudioSelectedLineActions({
    ...state,
    ...lineActions,
    ...playback,
    ...characterActions,
    ...autoRender,
  });
  const regenerateDictionaryLines = useDictionaryRegeneration({ ...state, ...lineActions, ...playback });
  const castImport = useCastImport(state);
  const controller = {
    ...state,
    ...projectEditing,
    ...lineActions,
    ...playback,
    ...characterActions,
    ...autoRender,
    ...jobActions,
    ...history,
    ...selectedLineActions,
    replaceLineTexts,
    regenerateDictionaryLines,
    ...castImport,
  };
  useStudioPlaybackDisplay(controller);
  useStudioEffects(controller);
  useStudioShortcuts(controller);
  return controller;
}

export type StudioController = ReturnType<typeof useStudioController>;
