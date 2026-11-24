import { api } from "../../api";
import type { DraftJob, StudioProject } from "../../types";
import type { ProjectOperation } from "./projectEditSession";
import type { StudioJobModel } from "./studioJobModel";
import { createRenderJob, enqueueRenderJobs, nextRenderSequence } from "./renderJobQueue";

export function forceAiDirectionAutoRender(model: StudioJobModel, nextProject: StudioProject, lineIds: string[], takeMode: "replace" | "append" | "none", operation: ProjectOperation) {
  if (!model.editSession.applyServer(operation, nextProject)) return;
  if (!lineIds.length || takeMode === "none") return;
  model.autoGenerateEnabledRef.current = true;
  model.setAutoGenerateEnabled(true);
  const jobs = nextProject.scenes
    .flatMap((scene) => scene.lines)
    .filter((line) => lineIds.includes(line.id))
    .map((line) => createRenderJob(nextProject, line, nextRenderSequence(), { mode: takeMode, cause: "ai-direction", targetTakeId: takeMode === "replace" ? (line.selectedTakeId ?? undefined) : undefined }, model.editSession.capture().generation));
  model.autoRenderQueue.current = enqueueRenderJobs(model.autoRenderQueue.current, jobs);
  model.setNotice("AI演出で変更した発話行を自動生成しています…");
  void model.processAutoRenderQueueRef.current();
}
export function startDraftJob(model: StudioJobModel, job: DraftJob) {
  model.stop();
  model.setDraftJob(job);
  model.setBusy("draft");
  model.setNotice("AI台本の全体構成を設計しています。生成した台本は自動で追加されます。");
}
export async function applyGlobalCastUpdates(model: StudioJobModel) {
  if (!model.globalCastUpdates?.length) return;
  model.setBusy("apply-global-cast-updates");
  try {
    const updated = await model.editSession.requestProject(() => api.applyGlobalCastUpdates(model.globalCastUpdates!.map(({ id }) => id)));
    if (!updated) return;
    model.setGlobalCastUpdates(null);
    model.setNotice("最新のグローバルキャスト情報をプロジェクトへ適用しました。");
  } catch (error) {
    model.setNotice(`グローバルキャストを適用できませんでした: ${(error as Error).message}`);
  } finally {
    model.setBusy(null);
  }
}
