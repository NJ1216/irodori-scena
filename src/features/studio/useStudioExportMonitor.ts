import { useEffect, useRef } from "react";
import { api } from "../../api";
import type { DialogueLine, ExportJob } from "../../types";
import { isTerminalJob, monitorJobEvents, snapshotFromProgressEvent, updatesAfterVersion } from "./jobEventMonitor";
import type { StudioEffectModel } from "./studioEffectTypes";

function applyLineUpdates(model: StudioEffectModel, operation: ReturnType<StudioEffectModel["editSession"]["capture"]>, updates: NonNullable<ExportJob["lineUpdates"]>) {
  model.editSession.applyServerUpdate(operation, (current) => {
    const byScene = new Map<string, Map<string, DialogueLine>>();
    for (const update of updates) {
      const byLine = byScene.get(update.sceneId) ?? new Map<string, DialogueLine>();
      byLine.set(update.line.id, update.line);
      byScene.set(update.sceneId, byLine);
    }
    return {
      ...current,
      scenes: current.scenes.map((scene) => {
        const byLine = byScene.get(scene.id);
        return byLine ? { ...scene, lines: scene.lines.map((line) => byLine.get(line.id) ?? line) } : scene;
      }),
    };
  });
}

export function useStudioExportMonitor(model: StudioEffectModel) {
  const modelRef = useRef(model);
  const jobRef = useRef(model.exportJob);
  const { exportJob, editSession, exportUpdateVersion, setExportJob, setBusy, setNotice, setAutoGenerateEnabled } = model;
  useEffect(() => {
    modelRef.current = model;
    jobRef.current = exportJob;
  }, [exportJob, model]);
  useEffect(() => {
    const monitoredJob = jobRef.current;
    if (!monitoredJob || !["preparing", "generating", "aligning", "writing"].includes(monitoredJob.status)) return;
    const controller = new AbortController();
    const operation = editSession.capture();
    const active = () => {
      if (!editSession.isCurrent(operation)) controller.abort();
      return !controller.signal.aborted;
    };
    const applySnapshot = async (next: ExportJob) => {
      if (!active()) return;
      const updates = updatesAfterVersion(next.lineUpdates, exportUpdateVersion.current);
      if (updates.length) applyLineUpdates(modelRef.current, operation, updates);
      exportUpdateVersion.current = Math.max(exportUpdateVersion.current, next.updateVersion ?? 0);
      if (isTerminalJob(next)) {
        const latest = await api.project();
        if (!controller.signal.aborted) editSession.applyServer(operation, latest);
      }
      if (!active()) return;
      setExportJob(next);
      if (["completed", "completed_with_warnings"].includes(next.status)) {
        setBusy(null);
        setNotice(next.message);
      } else if (["failed", "cancelled"].includes(next.status)) {
        if (!next.joinOutput) setAutoGenerateEnabled(false);
        setBusy(null);
        setNotice(next.status === "failed" ? `まとめてエクスポートが途中で止まりました: ${next.error || "生成設定を確認してください。"}` : "まとめてエクスポートをキャンセルしました。生成済みの行は個別に再生できます。");
      }
    };
    void monitorJobEvents({
      jobId: monitoredJob.id,
      signal: controller.signal,
      stream: (onEvent, options) => api.exportJobEvents(monitoredJob.id, onEvent, options),
      poll: () => {
        if (!active()) throw new DOMException("Project changed", "AbortError");
        return api.exportJob(monitoredJob.id, exportUpdateVersion.current);
      },
      onSnapshot: applySnapshot,
      isTerminal: isTerminalJob,
      snapshotFromEvent: snapshotFromProgressEvent<ExportJob>,
      pollIntervalMs: 1500,
      maxStreamAttempts: 2,
    }).catch((error) => {
      if (active()) {
        setBusy(null);
        setNotice(`エクスポートの進捗を確認できません: ${(error as Error).message}`);
      }
    });
    return () => controller.abort();
  }, [editSession, exportJob?.id, exportUpdateVersion, setAutoGenerateEnabled, setBusy, setExportJob, setNotice]);
}
