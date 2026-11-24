import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { projectMenuActionLabel, type ProjectMenuAction } from "./projectMenuActionTypes";

export function AutoGenerationConflictDialog({ action, onClose, onContinue }: { action: ProjectMenuAction; onClose: () => void; onContinue: () => void }) {
  const label = projectMenuActionLabel[action];
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal project-maintenance-confirm" role="dialog" aria-modal="true" aria-label={`自動生成を停止して${label}を続行`}>
        <DialogHeader eyebrow="AUTO GENERATION" title="自動生成を停止して続行しますか？" description="未処理の自動生成キューは破棄します。生成済みテイクは保持されます。" />
        <DialogFooter>
          <button type="button" onClick={onClose}>
            キャンセル
          </button>
          <button className="primary" onClick={onContinue}>
            {label}を続行
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
