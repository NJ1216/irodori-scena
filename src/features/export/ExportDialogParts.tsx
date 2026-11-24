import type { ExportJob } from "../../types";
import { DialogFooter } from "../shared/overlays";

export function ExportProgress({ job }: { job: ExportJob }) {
  if (job.status === "writing") {
    return (
      <div className="export-progress">
        <progress />
      </div>
    );
  }
  const aligning = job.status === "aligning";
  const current = (aligning ? job.alignmentCompletedLines : job.completedLines) ?? 0;
  const total = (aligning ? job.alignmentTotalLines : job.totalLines) || 1;
  const label = job.status === "generating" ? `発話 ${current} / ${job.totalLines} 行` : "";
  return (
    <div className="export-progress">
      <progress max={total} value={current} />
      {label && <p>{label}</p>}
    </div>
  );
}

export function ExportFooter({ running, done, invalid, cancelRequested, onClose, onCancel, onStart }: { running: boolean; done: boolean; invalid: boolean; cancelRequested: boolean; onClose: () => void; onCancel: () => Promise<void> | void; onStart: () => Promise<void> }) {
  let label = "キャンセル";
  if (running && cancelRequested) label = "キャンセル中…";
  else if (done) label = "閉じる";
  return (
    <DialogFooter className="export-dialog-footer">
      <button type="button" disabled={running && cancelRequested} onClick={running ? () => void onCancel() : onClose}>
        {label}
      </button>
      {!done && !running && (
        <button type="button" className="primary" disabled={invalid} onClick={() => void onStart()}>
          エクスポート
        </button>
      )}
    </DialogFooter>
  );
}

export function ExportResult({ job }: { job: ExportJob | null }) {
  return (
    <div className="export-result">
      <p>
        <b>保存先:</b> {job?.destinationPath}
      </p>
      {!!job?.labFailures?.length && (
        <div className="warning-text" role="alert">
          <b>生成できなかった口パクLAB: {job.labFailures.length}件</b>
          <ul>
            {job.labFailures.map((failure) => (
              <li key={`${failure.lineId}-${failure.lineNumber}`}>
                {failure.lineNumber}行目: {failure.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
