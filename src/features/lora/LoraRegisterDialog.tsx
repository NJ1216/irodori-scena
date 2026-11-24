import { useLoraDialogAction } from "./loraDialogActionHook";
import { useLoraRegisterFocus } from "./useLoraRegisterFocus";
import { useState } from "react";
import { createPortal } from "react-dom";
import { chooseDirectory } from "../../api";
import { loraApi } from "../../api-lora";
import type { LoraAsset } from "../../types/lora";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import "../../styles/lora.css";

export function LoraRegisterDialog({ onRegistered, onClose }: { onRegistered: (asset: LoraAsset) => void; onClose: () => void }) {
  const [path, setPath] = useState("");
  const [name, setName] = useState("");
  const [memo, setMemo] = useState("");
  const { busy, error, perform } = useLoraDialogAction();
  const [completed, setCompleted] = useState(false);
  const dialogRef = useLoraRegisterFocus(busy, completed);
  async function choose() {
    await perform(async () => {
      const selected = await chooseDirectory("LoRAフォルダを選択", path || undefined);
      if (selected) setPath(selected);
    });
  }
  async function register(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    event.stopPropagation(); // Portal submit must never submit the parent cast editor.
    await perform(async () => {
      if (!path.trim() || !name.trim()) throw new Error("フォルダとLoRA名を指定してください。");
      const status = await loraApi.status();
      if (!status.baseModelRepo || !status.baseModelRevision) throw new Error("本体モデルを確認できません。");
      const asset = await loraApi.importAdapter({ path, name, memo, baseModelRepo: status.baseModelRepo, baseModelRevision: status.baseModelRevision });
      onRegistered(asset);
      setCompleted(true);
    });
  }
  return createPortal(
    <ModalBackdrop onClose={onClose} disabled={busy}>
      <form ref={dialogRef} tabIndex={-1} className="modal lora-register-dialog" role="dialog" aria-modal="true" aria-labelledby="lora-register-title" onSubmit={(event) => void register(event)}>
        <DialogHeader titleId="lora-register-title" eyebrow="REGISTER LORA" title={completed ? "LoRAを登録しました" : "LoRAを登録"} description={completed ? "キャストのLoRA選択欄から選んでください。" : "LoRAのフォルダを選び、管理する名前をつけます。"} />
        {!completed && (
          <div className="lora-register-fields">
            <label className="dialog-form-field">
              LoRAフォルダ
              <div className="lora-register-path">
                <input value={path} onChange={(event) => setPath(event.target.value)} disabled={busy} />
                <button type="button" className="secondary" disabled={busy} onClick={() => void choose()}>
                  選択
                </button>
              </div>
            </label>
            <label className="dialog-form-field">
              LoRA名
              <input value={name} onChange={(event) => setName(event.target.value)} disabled={busy} />
            </label>
            <label className="dialog-form-field">
              管理メモ（任意）
              <textarea value={memo} onChange={(event) => setMemo(event.target.value)} disabled={busy} />
            </label>
          </div>
        )}
        {error && (
          <p role="alert" className="warning-text">
            {error}
          </p>
        )}
        <DialogFooter>
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            {completed ? "閉じる" : "キャンセル"}
          </button>
          {!completed && (
            <button type="submit" className="primary" disabled={busy || !path.trim() || !name.trim()}>
              {busy ? "処理中…" : "登録する"}
            </button>
          )}
        </DialogFooter>
      </form>
    </ModalBackdrop>,
    document.body,
  );
}
