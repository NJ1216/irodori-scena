import type { StudioAutoRenderActions } from "./useStudioAutoRender";
import type { StudioProjectEditingActions } from "./useStudioProjectEditing";
import type { StudioState } from "./useStudioState";

export type StudioEffectModel = StudioState & StudioProjectEditingActions & StudioAutoRenderActions;
