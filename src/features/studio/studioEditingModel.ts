import type { StudioState } from "./useStudioState";
import { useStudioEditingInteractions } from "./useStudioEditingInteractions";

export type StudioEditingModel = Pick<StudioState, "editSession" | "projectRef" | "autoGenerateEnabledRef" | "autoRenderQueue" | "autoRenderInProgress" | "autoRenderActiveLineId" | "processAutoRenderQueueRef" | "busyRef" | "setNotice" | "projectSavePendingCount"> & Parameters<typeof useStudioEditingInteractions>[0];
