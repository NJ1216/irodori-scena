import { api } from "../../api";
import type { DraftJob } from "../../types";
import { DraftGenerationDialog } from "../draft/DraftStatus";

export function AiDirectionProgressDialog({ job, running, setJob, onClose }: { job: DraftJob; running: boolean; setJob: (job: DraftJob) => void; onClose: () => void }) {
  return (
    <DraftGenerationDialog
      job={job}
      elapsed={0}
      generatedCharacters={job.performanceCompletedLines}
      targetCharacters={job.performanceTotalLines}
      overallProgress={job.performanceTotalLines ? (job.performanceCompletedLines / job.performanceTotalLines) * 100 : 0}
      onCancel={async () => setJob(await api.cancelAiJob(job.id))}
      eyebrow="AI DIRECTION"
      title="AI演出を反映しています"
      phases={[["direction", "選択した発話行を演出しています"]]}
      progressLabel="AI演出の進捗"
      progressMetrics={
        <div className="draft-generation-progress-metrics">
          <span>{job.message}</span>
          <span>
            演技設定 {job.performanceCompletedLines} / {job.performanceTotalLines}行
          </span>
        </div>
      }
      indeterminate={false}
      cancelLabel="AI演出をキャンセル"
      actionLabel={running ? undefined : "閉じる"}
      onAction={running ? undefined : onClose}
    />
  );
}
