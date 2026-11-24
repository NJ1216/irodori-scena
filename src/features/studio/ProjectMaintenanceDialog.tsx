import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";

type Action = "new" | "takes";

const content: Record<Action, { label: string; title: string; confirm: string; description: string }> = {
  new: {
    label: "新規プロジェクトを作成",
    title: "新規プロジェクトを作成しますか？",
    confirm: "新規作成",
    description: "現在の台本を閉じ、新しいプロジェクトを開始します。登録済みのグローバルキャストは引き続き利用できます。",
  },
  takes: {
    label: "生成テイクを初期化",
    title: "生成テイクを初期化しますか？",
    confirm: "生成テイクを初期化",
    description: "すべての生成テイクを削除します。台本、キャスト、参照WAVは残ります。",
  },
};

export function ProjectMaintenanceDialog({ action, onClose, onConfirm }: { action: Action; onClose: () => void; onConfirm: () => void }) {
  const details = content[action];
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal project-maintenance-confirm" role="dialog" aria-modal="true" aria-label={details.label}>
        <DialogHeader eyebrow="PROJECT MAINTENANCE" title={details.title} description={details.description} />
        <DialogFooter>
          <button type="button" onClick={onClose}>
            キャンセル
          </button>
          <button className="primary" onClick={onConfirm}>
            {details.confirm}
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
