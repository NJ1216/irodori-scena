import type { StudioAutoRenderActions } from "./useStudioAutoRender";
import type { StudioCharacterActions } from "./useStudioCharacterActions";
import type { StudioLineActions } from "./useStudioLineActions";
import type { StudioPlaybackActions } from "./useStudioPlayback";
import type { StudioProjectEditingActions } from "./useStudioProjectEditing";
import type { StudioState } from "./useStudioState";

export type StudioJobModel = StudioState & StudioProjectEditingActions & StudioLineActions & StudioPlaybackActions & StudioCharacterActions & StudioAutoRenderActions;
