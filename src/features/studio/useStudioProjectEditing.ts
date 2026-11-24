import { createStudioBatchEditingActions } from "./studioBatchEditingActions";
import { createStudioCandidateCleanupActions } from "./studioCandidateCleanupActions";
import type { StudioEditingModel } from "./studioEditingModel";
import { useStudioEditingInteractions } from "./useStudioEditingInteractions";
import { createStudioLineCommitActions } from "./studioLineCommitActions";
import { createStudioPersistenceActions } from "./studioPersistenceActions";

export function useStudioProjectEditing(model: StudioEditingModel) {
  const lineCommit = createStudioLineCommitActions(model);
  const persistence = createStudioPersistenceActions(model, lineCommit.queueAutoRender);
  const batch = createStudioBatchEditingActions(model, persistence.updateProject, lineCommit.queueAutoRender);
  const candidates = createStudioCandidateCleanupActions(model);
  return {
    ...useStudioEditingInteractions(model, candidates.clearCandidates),
    ...persistence,
    ...batch,
    ...lineCommit,
    ...candidates,
  };
}

export type StudioProjectEditingActions = ReturnType<typeof useStudioProjectEditing>;
