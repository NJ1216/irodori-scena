import type { ExportJob, StudioProject } from "../../types";
import { DialogHeader, ModalBackdrop } from "../shared/overlays";
import { RhubarbDialog } from "../settings/RhubarbSetting";
import { ExportFooter, ExportProgress, ExportResult } from "./ExportDialogParts";
import { ExportSettingsForm } from "./ExportSettingsForm";
import type { Settings } from "./exportSettings";
import { useExportDialogState } from "./useExportDialogState";

function exportTitle(done: boolean, running: boolean) {
  if (done) return "エクスポート結果";
  return running ? "エクスポート中" : "エクスポート";
}

function exportDescription(done: boolean, running: boolean, job: ExportJob | null) {
  if (done) return "下記フォルダにファイルを保存しました。";
  return running ? job?.message : "必要な成果物をまとめて設定します。";
}

export function ExportDialog({ project, job, onClose, onStart, onCancel }: { project: StudioProject; job: ExportJob | null; onClose: () => void; onStart: (settings: Settings & { destinationDir: string }) => Promise<unknown>; onCancel: () => Promise<void> | void }) {
  const state = useExportDialogState(project, job, onStart);
  const { running, done, rhubarbPrompt } = state;
  return (
    <>
      {!rhubarbPrompt && (
        <ModalBackdrop onClose={running ? () => {} : onClose} disabled={running}>
          <section className="modal export-dialog" role="dialog" aria-modal="true" aria-label="エクスポート">
            <DialogHeader eyebrow="EXPORT" title={exportTitle(done, running)} description={exportDescription(done, running, job)} />
            {done ? (
              <ExportResult job={job} />
            ) : running ? (
              <ExportProgress job={job!} />
            ) : (
              <ExportSettingsForm settings={state.settings} previews={state.previews} duplicate={state.duplicate} destinationDir={state.destinationDir} error={state.error} update={state.update} onToggleFormat={state.toggleFormat} onSelectLayout={state.selectLayout} onDestinationChange={state.setDestinationDir} />
            )}
            <ExportFooter running={running} done={done} invalid={state.invalid} cancelRequested={Boolean(job?.cancelRequested)} onClose={onClose} onCancel={onCancel} onStart={state.start} />
          </section>
        </ModalBackdrop>
      )}
      {rhubarbPrompt && (
        <RhubarbDialog
          exportMode
          status={rhubarbPrompt}
          onClose={() => state.setRhubarbPrompt(null)}
          onChanged={state.setRhubarbPrompt}
          onReady={() => {
            state.setRhubarbPrompt(null);
            void state.submit();
          }}
        />
      )}
    </>
  );
}
