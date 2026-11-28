import type { ReactNode } from "react";
import { DraftGenerationDialog } from "../draft/DraftStatus";
import { DialogFooter } from "../shared/overlays";
import { FormError } from "../shared/InlineValidation";
import type { ScriptAssistantJob } from "./scriptAssistantTypes";

export function LineAssistantProgress({ job, insert, onCancel }: { job: ScriptAssistantJob; insert: boolean; onCancel: () => Promise<void> }) {
  return (
    <DraftGenerationDialog
      job={job}
      elapsed={0}
      generatedCharacters={0}
      targetCharacters={0}
      overallProgress={job.overallProgress}
      onCancel={onCancel}
      eyebrow="AI SCRIPT EDIT"
      title={insert ? "発話行を生成しています" : "選択行を書き直しています"}
      phases={
        job.operation === "rewrite"
          ? [
              ["context", "台本の文脈を整理しています"],
              ["rewrite-plan", "書き直し方針を組み立てています"],
              ["dialogue", "提案を生成しています"],
            ]
          : [
              ["context", "台本の文脈を整理しています"],
              ["dialogue", "提案を生成しています"],
            ]
      }
      progressLabel="AI台本編集の全体進捗"
      progressMetrics={
        <div className="draft-generation-progress-metrics">
          <span>{job.message}</span>
          <span>全体進捗 {Math.floor(job.overallProgress)}%</span>
        </div>
      }
      cancelLabel="生成をキャンセル"
    />
  );
}

export function LineAssistantFooter({
  error = "",
  preview,
  running,
  insert,
  busy,
  canApply,
  onClose,
  onBackToSettings,
  onApply,
  onGenerate,
}: {
  error?: string;
  preview: boolean;
  running: boolean;
  insert: boolean;
  busy: string | null;
  canApply: boolean;
  onClose: () => void;
  onBackToSettings: () => void;
  onApply: () => void;
  onGenerate: () => void;
}) {
  let actions: ReactNode = null;
  if (preview) {
    actions = (
      <>
        <button type="button" disabled={Boolean(busy)} onClick={onBackToSettings}>
          設定に戻る
        </button>
        <button className="primary" disabled={Boolean(busy) || !canApply} onClick={onApply}>
          選択した提案を適用
        </button>
      </>
    );
  } else if (!running && !insert) {
    actions = (
      <button className="primary" disabled={Boolean(busy)} onClick={onGenerate}>
        ✦ 提案を生成
      </button>
    );
  }
  return (
    <DialogFooter leading={error ? <FormError message={error} /> : undefined}>
      <button type="button" disabled={busy === "script-assistant-apply"} onClick={onClose}>
        閉じる
      </button>
      {actions}
    </DialogFooter>
  );
}
