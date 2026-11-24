import { api } from "../../api";
import type { StudioJobModel } from "./studioJobModel";
import { useJobCancellation } from "./useJobCancellation";

async function handleStartExportError(model: StudioJobModel, joinOutput: boolean, autoGenerationRequest: number | undefined, error: unknown) {
  const message = (error as Error).message;
  if (!joinOutput && !model.autoGenerateEnabledRef.current && message.includes("まとめてエクスポートが進行中です")) {
    try {
      await api.cancelActiveExportJob();
      model.setNotice("残っていた自動生成を停止しました。もう一度ONにできます。");
    } catch (cancelError) {
      model.setNotice(`残っていた自動生成を停止できません: ${(cancelError as Error).message}`);
    }
    return;
  }
  if (!joinOutput && (autoGenerationRequest === undefined || autoGenerationRequest === model.autoGenerationRequestRef.current)) {
    model.autoGenerateEnabledRef.current = false;
    model.setAutoGenerateEnabled(false);
  }
  model.setNotice(`${joinOutput ? "WAVのエクスポート" : "自動生成"}を開始できません: ${message}`);
}

export function useStudioExportActions(model: StudioJobModel) {
  const { exportUpdateVersion: exportUpdateVersionRef } = model;
  async function startExport(joinOutput: boolean, autoGenerationRequest?: number, _mode?: "prepare" | "individual" | "joined", afterAutoStop = false) {
    if (model.busy && !afterAutoStop) return model.setNotice("実行中の処理が完了してから実行してください。");
    model.stop();
    try {
      const job = await model.editSession.runServer(() => api.startExportJob());
      if (!job) return;
      if (autoGenerationRequest !== undefined && autoGenerationRequest !== model.autoGenerationRequestRef.current) {
        void api.cancelExportJob(job.id);
        return;
      }
      exportUpdateVersionRef.current = job.updateVersion ?? 0;
      model.setExportJob(job);
      model.setBusy("export");
      model.setNotice(joinOutput ? "WAVのエクスポートを開始しました。未生成行は台本順に生成します。" : "未生成行を台本順に自動生成します。");
    } catch (error) {
      await handleStartExportError(model, joinOutput, autoGenerationRequest, error);
    }
  }
  const cancelExport = useJobCancellation({
    job: model.exportJob,
    editSession: model.editSession,
    request: api.cancelExportJob,
    setNotice: model.setNotice,
    pendingMessage: "エクスポートのキャンセルを受け付けました。現在の発話行を完了後に停止します…",
    failurePrefix: "エクスポートをキャンセルできません",
  });
  async function startExportBundle(settings: Parameters<typeof api.startExportBundle>[0]) {
    if (model.busy) throw new Error("実行中の処理が完了してからエクスポートしてください。");
    model.stop();
    const job = await model.editSession.runServer(() => api.startExportBundle(settings));
    if (!job) return;
    exportUpdateVersionRef.current = job.updateVersion ?? 0;
    model.setExportJob(job);
    model.setBusy("export");
    model.setNotice("エクスポートを開始しました。");
    return job;
  }
  return { startExport, cancelExport, startExportBundle };
}
