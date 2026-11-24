import { selectedTake } from "../shared/studio-utils";
import type { StudioJobModel } from "./studioJobModel";
import { createRenderJob, enqueueRenderJobs, nextRenderSequence } from "./renderJobQueue";

export function useStudioAutoGenerationActions(model: StudioJobModel, cancelExport: () => Promise<void>) {
  function queueMissing() {
    const project = model.projectRef.current;
    const lines = project?.scenes.flatMap((scene) => scene.lines).filter((line) => line.enabled !== false && line.text.trim() && line.characterId && line.takes.length === 0 && !selectedTake(line)) ?? [];
    if (!project) return;
    const generation = model.editSession.capture().generation;
    const jobs = lines.map((line) => createRenderJob(project, line, nextRenderSequence(), { mode: "append", cause: "missing-take" }, generation));
    model.autoRenderQueue.current = enqueueRenderJobs(model.autoRenderQueue.current, jobs);
  }
  function stopQueued() {
    model.autoGenerationRequestRef.current += 1;
    model.autoGenerateEnabledRef.current = false;
    model.setAutoGenerateEnabled(false);
    model.autoRenderQueue.current = [];
    model.setNotice("自動生成を停止します。現在の発話行を完了後、残りの行は生成しません。");
  }
  function toggleAutoGeneration() {
    if (model.busy === "export") {
      if (model.exportJob?.joinOutput) {
        model.setNotice("WAV保存を処理中です。停止するにはこのボタンをもう一度押してください。");
        void cancelExport();
        return;
      }
      stopQueued();
      void cancelExport();
      return;
    }
    if (model.autoGenerateEnabled) {
      stopQueued();
      return;
    }
    if (model.busy) {
      model.autoGenerateEnabledRef.current = true;
      model.setAutoGenerateEnabled(true);
      queueMissing();
      model.setNotice("自動生成をONにしました。現在の処理が完了後、未生成の発話行を生成します。");
      return;
    }
    const next = !model.autoGenerateEnabled;
    model.autoGenerateEnabledRef.current = next;
    model.setAutoGenerateEnabled(next);
    if (!next) {
      model.autoRenderQueue.current = [];
      return;
    }
    queueMissing();
    void model.processAutoRenderQueueRef.current();
    model.setNotice("自動生成をONにしました。未生成行と、以後に確定した本文を順に生成します。");
  }
  return { toggleAutoGeneration };
}
