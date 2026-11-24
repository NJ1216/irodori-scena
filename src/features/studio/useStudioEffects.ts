import type { StudioEffectModel } from "./studioEffectTypes";
import { useStudioBootstrap } from "./useStudioBootstrap";
import { useStudioDraftMonitor } from "./useStudioDraftMonitor";
import { useStudioExportMonitor } from "./useStudioExportMonitor";
import { useStudioInteractionEffects } from "./useStudioInteractionEffects";

export function useStudioEffects(model: StudioEffectModel) {
  useStudioBootstrap(model);
  useStudioDraftMonitor(model);
  useStudioExportMonitor(model);
  useStudioInteractionEffects(model);
}
