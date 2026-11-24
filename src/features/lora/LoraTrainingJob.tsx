import type { LoraTrainingModel } from "./LoraTrainingView";
import { runningJob } from "./loraDraft";
import { jobLabels } from "./loraJobLabels";

export function TrainingJob({ model, job }: { model: LoraTrainingModel; job?: LoraTrainingModel["jobs"][number] }) {
  if (!job) return <p role="status">学習状況を確認しています…</p>;
  return (
    <div className="lora-job-result">
      <h3>{job.name}</h3>
      <p role="status">{jobLabels[job.status] ?? job.status}</p>
      {runningJob(job.status) && (
        <>
          <p className="subtle">
            {job.step ?? 0} / {job.totalSteps ?? "—"} ステップ。画面を離れても学習は続きます。
          </p>
          <button type="button" className="secondary" disabled={model.busy || job.status === "cancelling"} onClick={() => void model.cancel(job.id)}>
            学習を中断
          </button>
        </>
      )}
      {job.status === "completed" && <p className="subtle">保存しました。キャスト編集で選択できます。</p>}
      {job.error && (
        <p role="alert" className="warning-box">
          {job.error}
        </p>
      )}
    </div>
  );
}
