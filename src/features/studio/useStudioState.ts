import { useAutoGenerationState, useDialogJobState, usePlaybackSelectionState, useProjectWorkspaceState, useScrollFocusState } from "./studioStateDomains";

export function useStudioState() {
  const projectWorkspace = useProjectWorkspaceState();
  const autoGeneration = useAutoGenerationState();
  const dialogJob = useDialogJobState();
  const playbackSelection = usePlaybackSelectionState();
  const scrollFocus = useScrollFocusState();
  const { project } = projectWorkspace;
  const { busy, exportJob } = dialogJob;
  const { batchGeneratingLineId, playingLineId } = playbackSelection;
  const { autoScrollTarget } = scrollFocus;
  const generatingLineId = busy === "export" ? (exportJob?.currentLineId ?? null) : project?.scenes?.some((scene) => scene.lines.some((line) => line.id === busy)) ? busy : batchGeneratingLineId;
  const autoScrollLineId = autoScrollTarget === "playback" ? playingLineId : generatingLineId;
  return { ...projectWorkspace, ...autoGeneration, ...dialogJob, ...playbackSelection, ...scrollFocus, generatingLineId, autoScrollLineId };
}

export type StudioState = ReturnType<typeof useStudioState>;
