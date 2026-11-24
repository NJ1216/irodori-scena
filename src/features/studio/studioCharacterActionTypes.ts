import type { StudioLineActions } from "./useStudioLineActions";
import type { StudioPlaybackActions } from "./useStudioPlayback";
import type { StudioProjectEditingActions } from "./useStudioProjectEditing";
import type { StudioState } from "./useStudioState";

export type CharacterActionModel = StudioState & StudioProjectEditingActions & StudioLineActions & StudioPlaybackActions;
