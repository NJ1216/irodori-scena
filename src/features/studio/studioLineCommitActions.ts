import type { StudioEditingModel } from "./studioEditingModel";
import { createRenderJob, enqueueRenderJobs, lineRenderSignature, nextRenderSequence } from "./renderJobQueue";
import { api } from "../../api";
import type { StudioProject } from "../../types";

type QueueOptions = { mode?: "append" | "replace"; cause?: "manual-new-take" | "manual-replace" | "manual-seed" | "last-take-deleted" | "line-edited"; seed?: number; targetTakeId?: string; historyBaseRevision?: number };

function renderMode(options: QueueOptions | undefined, selectedTakeId: string | null, takeCount: number) {
  if (options?.mode) return options.mode;
  if (options?.targetTakeId || selectedTakeId) return "replace";
  return takeCount ? null : "append";
}

function createQueuedJob(model: StudioEditingModel, lineId: string, options?: QueueOptions) {
  const project = model.projectRef.current;
  const line = project?.scenes.flatMap((scene) => scene.lines).find((item) => item.id === lineId);
  if (!project || !line) return null;
  const targetTakeId = options?.targetTakeId ?? line.selectedTakeId ?? undefined;
  const mode = renderMode(options, line.selectedTakeId, line.takes.length);
  if (!mode) return null;
  return createRenderJob(project, line, nextRenderSequence(), { mode, cause: options?.cause ?? "line-edited", seed: options?.seed, targetTakeId: mode === "replace" ? targetTakeId : undefined, historyBaseRevision: options?.historyBaseRevision }, model.editSession.capture().generation);
}

function lineContentChanged(beforeProject: StudioProject | null, afterProject: StudioProject | null, lineId: string) {
  const before = beforeProject?.scenes.flatMap((scene) => scene.lines).find((line) => line.id === lineId);
  const after = afterProject?.scenes.flatMap((scene) => scene.lines).find((line) => line.id === lineId);
  return Boolean(beforeProject && before && afterProject && after && lineRenderSignature(beforeProject, before) !== lineRenderSignature(afterProject, after));
}

export function createStudioLineCommitActions(model: StudioEditingModel) {
  function queueAutoRender(lineId: string, options?: QueueOptions) {
    if (!model.autoGenerateEnabledRef.current) return;
    const job = createQueuedJob(model, lineId, options);
    if (!job) return;
    model.autoRenderQueue.current = enqueueRenderJobs(model.autoRenderQueue.current, [job]);
    if (job.cause === "line-edited" && model.autoRenderInProgress.current && model.autoRenderActiveLineId.current === lineId) void api.cancelAutoRender(lineId).catch(() => undefined);
    void model.processAutoRenderQueueRef.current();
  }
  async function commitLineContent(lineId: string, autoRender: boolean) {
    const savedProject = model.editSession.savedProject();
    const before = savedProject?.scenes.flatMap((scene) => scene.lines).find((line) => line.id === lineId);
    const targetTakeId = before?.selectedTakeId ?? undefined;
    if (!model.editSession.commitLine(lineId)) return model.editSession.waitForPersistence();
    const changed = lineContentChanged(savedProject, model.projectRef.current, lineId);
    const operation = model.editSession.capture();
    const saved = await model.editSession.save(model.busyRef.current === "export" ? "発話内容を確定しました。エクスポートキューで再生成します。" : "発話内容を確定しました。", "発話内容を確定できませんでした");
    if (!saved || !model.editSession.isCurrent(operation)) return false;
    if (autoRender && changed && model.busyRef.current !== "export") queueAutoRender(lineId, { targetTakeId });
    return true;
  }
  return { queueAutoRender, commitLineContent };
}
