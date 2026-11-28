import { useEffect, useRef } from "react";
import { api } from "../../api";
import type { DraftJob } from "../../types";
import { isTerminalJob, monitorJobEvents, snapshotFromProgressEvent } from "./jobEventMonitor";
import type { StudioEffectModel } from "./studioEffectTypes";

function disableAutoGeneration(model: StudioEffectModel) {
  model.autoGenerationRequestRef.current += 1;
  model.autoGenerateEnabledRef.current = false;
  model.setAutoGenerateEnabled(false);
  model.autoRenderQueue.current = [];
}

function complete(model: StudioEffectModel, job: DraftJob) {
  if ((job.mode ?? "draft") === "draft" && job.appendedLines > 0) {
    model.setTab("script");
    model.setDraftCompletionSummary((current) => (current?.id === job.id ? current : job));
  }
  model.setBusy(null);
  // The completion summary dialog already reports this, so it must not be overlaid on top of it.
  model.setStatusNotice("AI台本を台本へ追加しました。音声合成を再開できます。");
}

export function useStudioDraftMonitor(model: StudioEffectModel) {
  const modelRef = useRef(model);
  const jobRef = useRef(model.draftJob);
  const { draftJob, editSession, setDraftJob, setBusy, setNotice } = model;
  useEffect(() => {
    modelRef.current = model;
    jobRef.current = draftJob;
  }, [draftJob, model]);
  useEffect(() => {
    const monitoredJob = jobRef.current;
    if (!monitoredJob || !["planning", "generating"].includes(monitoredJob.status)) return;
    const controller = new AbortController();
    const operation = editSession.capture();
    const active = () => {
      if (!editSession.isCurrent(operation)) controller.abort();
      return !controller.signal.aborted;
    };
    let completedChunks = monitoredJob.completedChunks;
    const applySnapshot = async (next: DraftJob) => {
      if (!active()) return;
      const refresh = next.completedChunks > completedChunks || isTerminalJob(next);
      if (refresh) {
        const latest = await api.project();
        if (!controller.signal.aborted) editSession.applyServer(operation, latest);
      }
      if (!active()) return;
      completedChunks = Math.max(completedChunks, next.completedChunks);
      if (next.status === "completed" && (next.mode ?? "draft") === "draft") disableAutoGeneration(modelRef.current);
      setDraftJob(next);
      if (next.status === "completed") complete(modelRef.current, next);
      else if (next.status === "cancelled") {
        setBusy(null);
        setNotice("生成をキャンセルしました。台本は変更していません。");
      } else if (next.status === "failed") {
        setBusy(null);
        setNotice(`台本生成が途中で止まりました: ${next.error || "接続先の応答を確認してください。"}`);
      }
    };
    void monitorJobEvents({
      jobId: monitoredJob.id,
      signal: controller.signal,
      stream: (onEvent, options) => api.aiJobEvents(monitoredJob.id, onEvent, options),
      poll: () => {
        if (!active()) throw new DOMException("Project changed", "AbortError");
        return api.aiJob(monitoredJob.id);
      },
      onSnapshot: applySnapshot,
      isTerminal: isTerminalJob,
      snapshotFromEvent: snapshotFromProgressEvent<DraftJob>,
      pollIntervalMs: 1500,
      maxStreamAttempts: 2,
    }).catch((error) => {
      if (active()) {
        setBusy(null);
        setNotice(`台本生成の進捗を確認できません: ${(error as Error).message}`);
      }
    });
    return () => controller.abort();
  }, [draftJob?.id, editSession, setBusy, setDraftJob, setNotice]);
}
