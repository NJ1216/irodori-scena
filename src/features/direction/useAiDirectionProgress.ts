import { api } from "../../api";
import type { DraftJob, StudioProject } from "../../types";
import type { ProjectEditSession, ProjectOperation } from "../studio/projectEditSession";
import { useSequentialPolling } from "../shared/useSequentialPolling";

type Model = {
  running: boolean;
  job: DraftJob | null;
  setJob: (job: DraftJob) => void;
  operation: { current: ProjectOperation | null };
  projectSession: ProjectEditSession;
  takeMode: "replace" | "append" | "none";
  onClose: () => void;
  onNotice: (message: string) => void;
  onComplete: (project: StudioProject, lineIds: string[], mode: "replace" | "append" | "none", operation: ProjectOperation) => void;
};
function resultNotice(job: DraftJob, takeMode: Model["takeMode"]) {
  if (job.status === "completed") return takeMode === "none" || !job.renderLineIds?.length ? "AI演出を台本へ反映しました。" : "AI演出を反映し、自動生成を開始しました。";
  return job.performanceCompletedLines > 0 ? `AI演出を一部反映しました（適用済み ${job.performanceCompletedLines}行）。` : `AI演出を反映できませんでした: ${job.error || "応答を確認してください。"}`;
}

export function useAiDirectionProgress({ running, job, setJob, operation, projectSession, takeMode, onClose, onComplete, onNotice }: Model) {
  const token = operation.current;
  useSequentialPolling({
    enabled: running && !!job && !!token,
    intervalMs: 1000,
    poll: () => api.aiJob(job!.id),
    terminal: (next) => ["completed", "failed", "cancelled"].includes(next.status),
    onResult: async (next, signal) => {
      const active = () => !signal.aborted && !!token && operation.current === token && projectSession.isCurrent(token);
      if (!active() || !token || next.id !== job?.id) return;
      const applied = next.performanceCompletedLines > 0;
      const project = next.status === "completed" || (next.status === "failed" && applied) ? await api.project() : null;
      if (!active()) return;
      if (project) onComplete(project, next.renderLineIds ?? [], takeMode, token);
      setJob(next);
      if (next.status === "completed") {
        onNotice(resultNotice(next, takeMode));
        onClose();
      } else if (next.status === "failed") {
        onNotice(resultNotice(next, takeMode));
      }
    },
    onError: (error) => {
      if (token && operation.current === token && projectSession.isCurrent(token)) onNotice(`AI演出の進捗を確認できません: ${(error as Error).message}`);
    },
  });
}
