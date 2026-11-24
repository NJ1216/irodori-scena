import type { DraftJob, StudioProject } from "../../types";
import type { ProjectOperation } from "./projectEditSession";
import { applyGlobalCastUpdates, forceAiDirectionAutoRender, startDraftJob } from "./studioDedicatedJobActions";
import type { StudioJobModel } from "./studioJobModel";
import { useDraftJobCancellation } from "./useDraftJobCancellation";
import { useStudioAutoGenerationActions } from "./useStudioAutoGenerationActions";
import { useStudioExportActions } from "./useStudioExportActions";
import { useStudioMenuActions } from "./useStudioMenuActions";

export function useStudioJobActions(model: StudioJobModel) {
  const exportActions = useStudioExportActions(model);
  const autoGenerationActions = useStudioAutoGenerationActions(model, exportActions.cancelExport);
  const menuActions = useStudioMenuActions(model);
  const cancelDraftJob = useDraftJobCancellation({ draftJob: model.draftJob, setNotice: model.setNotice, editSession: model.editSession });
  return {
    forceAiDirectionAutoRender: (project: StudioProject, lineIds: string[], mode: "replace" | "append" | "none", operation: ProjectOperation) => forceAiDirectionAutoRender(model, project, lineIds, mode, operation),
    startDraftJob: (job: DraftJob) => startDraftJob(model, job),
    cancelDraftJob,
    ...exportActions,
    ...autoGenerationActions,
    ...menuActions,
    applyGlobalCastUpdates: () => applyGlobalCastUpdates(model),
  };
}

export type StudioJobActions = ReturnType<typeof useStudioJobActions>;
