import { api } from "../../api";
import type { StudioProject } from "../../types";
import { selectedTake } from "../shared/studio-utils";
import { createRenderJob, enqueueRenderJobs, nextRenderSequence } from "./renderJobQueue";
import type { StudioPlaybackActions } from "./useStudioPlayback";
import type { StudioLineActions } from "./useStudioLineActions";
import type { StudioState } from "./useStudioState";

type RegenerationMode = "append" | "replace";
type DictionaryRegenerationModel = Pick<StudioState, "projectRef" | "editSession" | "setBusy" | "setBatchGeneratingLineId" | "setNotice" | "setStatusNotice" | "autoGenerateEnabledRef" | "autoRenderQueue" | "processAutoRenderQueueRef"> & Pick<StudioPlaybackActions, "stop">;
type DictionaryRegenerationActions = DictionaryRegenerationModel & Pick<StudioLineActions, "applyGeneratedTake">;

function regenerableLineIds(project: StudioProject, lineIds: string[]) {
  const requested = new Set(lineIds);
  return project.scenes
    .flatMap((scene) => scene.lines)
    .filter((line) => requested.has(line.id) && line.enabled !== false && line.text.trim() && line.characterId && selectedTake(line))
    .map((line) => line.id);
}

export function useDictionaryRegeneration(model: DictionaryRegenerationActions) {
  const { projectRef, editSession, setBusy, setBatchGeneratingLineId, setNotice, setStatusNotice, stop, autoGenerateEnabledRef, autoRenderQueue, processAutoRenderQueueRef, applyGeneratedTake } = model;

  return async function regenerateDictionaryLines(lineIds: string[], mode: RegenerationMode) {
    const project = projectRef.current;
    if (!project) return;
    if (autoGenerateEnabledRef.current) {
      const requested = regenerableLineIds(project, lineIds);
      const requestedSet = new Set(requested);
      const jobs = project.scenes
        .flatMap((scene) => scene.lines)
        .filter((line) => requestedSet.has(line.id))
        .map((line) => createRenderJob(project, line, nextRenderSequence(), { mode, cause: "dictionary", targetTakeId: mode === "replace" ? (line.selectedTakeId ?? undefined) : undefined }, editSession.capture().generation));
      autoRenderQueue.current = enqueueRenderJobs(autoRenderQueue.current, jobs);
      setNotice(`${requested.length}行を辞書変更の再生成キューへ追加しました。`);
      void processAutoRenderQueueRef.current();
      return;
    }
    stop();
    let completed = 0;
    let failure = "";
    for (const lineId of lineIds) {
      const current = projectRef.current ?? project;
      const target = current.scenes.flatMap((scene) => scene.lines.map((line) => ({ sceneId: scene.id, line }))).find((item) => item.line.id === lineId);
      if (!target) continue;
      const line = target.line;
      const selectedExists = line.takes.some((take) => take.id === line.selectedTakeId);
      if (line.enabled === false || !line.text.trim() || !line.characterId || !selectedExists) continue;
      setBusy(lineId);
      setBatchGeneratingLineId(lineId);
      setStatusNotice(`辞書変更の影響行を再生成中です… ${completed + 1}/${lineIds.length}`);
      try {
        const take = await editSession.runServer(
          () => (mode === "replace" ? api.regenerateLine(lineId, current.settings.quality) : api.generateLine(lineId, current.settings.quality)),
          (value, operation) => applyGeneratedTake(target.sceneId, lineId, value, mode === "replace", operation),
        );
        if (!take) return;
        completed += 1;
      } catch (error) {
        failure = (error as Error).message;
        break;
      }
    }
    try {
      await editSession.requestProject(() => api.project());
    } finally {
      setBusy(null);
      setBatchGeneratingLineId(null);
    }
    if (failure) setNotice(`${completed}行を再生成したところで停止しました: ${failure}`);
    else setStatusNotice(`${completed}行を再生成しました。`);
  };
}
