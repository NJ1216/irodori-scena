type Props = { canManage: boolean; busy: boolean; pending: boolean; confirmationKey: string; onEdit: () => void; onContinue: () => void; onRegister: () => void; onDelete: () => void };
export function LoraLibraryToolbar({ canManage, busy, pending, confirmationKey, onEdit, onContinue, onRegister, onDelete }: Props) {
  return (
    <div className="tabs lora-library-toolbar" role="group" aria-label="LoRAの操作">
      <button type="button" disabled={!canManage || busy} onClick={onEdit}>
        名前とメモを編集
      </button>
      <button type="button" disabled={!canManage || busy} onClick={onContinue}>
        追加学習
      </button>
      <button type="button" disabled={busy} onClick={onRegister}>
        LoRAを登録
      </button>
      <button type="button" className={pending ? "danger is-confirming" : "danger"} disabled={!canManage || busy} data-destructive-confirmation-key={confirmationKey} onClick={onDelete}>
        削除
      </button>
    </div>
  );
}
