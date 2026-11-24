import { useState } from "react";
import { createPortal } from "react-dom";
import { loraApi } from "../../api-lora";
import type { LoraAsset } from "../../types/lora";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { useLoraDialogAction } from "./loraDialogActionHook";
import { useLoraRegisterFocus } from "./useLoraRegisterFocus";

export function LoraAssetEditDialog({ asset, onSaved, onClose }: { asset: LoraAsset; onSaved: (asset: LoraAsset) => void; onClose: () => void }) {
  const [name, setName] = useState(asset.name);
  const [memo, setMemo] = useState(asset.memo ?? "");
  const { busy, error, perform } = useLoraDialogAction();
  const ref = useLoraRegisterFocus(busy, false, '[aria-label="登録済みLoRA"]');
  return createPortal(
    <ModalBackdrop onClose={onClose} disabled={busy}>
      <form
        ref={ref}
        className="modal lora-register-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="lora-edit-title"
        onSubmit={(event) => {
          event.preventDefault();
          void perform(async () => {
            if (!name.trim()) throw new Error("LoRA名を入力してください。");
            onSaved(await loraApi.updateAdapter(asset.id, { name, memo }));
            onClose();
          });
        }}
      >
        <DialogHeader titleId="lora-edit-title" title="名前とメモを編集" />
        <div className="lora-register-fields">
          <label className="dialog-form-field">
            LoRA名
            <input value={name} maxLength={200} disabled={busy} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="dialog-form-field">
            管理メモ
            <textarea value={memo} maxLength={10000} disabled={busy} onChange={(event) => setMemo(event.target.value)} />
          </label>
        </div>
        {error && (
          <p role="alert" className="warning-text">
            {error}
          </p>
        )}
        <DialogFooter>
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            キャンセル
          </button>
          <button type="submit" className="primary" disabled={busy}>
            変更を保存
          </button>
        </DialogFooter>
      </form>
    </ModalBackdrop>,
    document.body,
  );
}
