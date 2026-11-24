import { useState } from "react";
import type { Character, ScriptCastContext } from "../../types";
import { avatarImageUrl } from "../shared/studio-utils";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";

export function ScriptCastContextDialog({ character, context, onClose, onSave }: { character: Character; context?: ScriptCastContext; onClose: () => void; onSave: (context: { role: string; description: string }) => void }) {
  const [role, setRole] = useState(context?.role ?? "");
  const [description, setDescription] = useState(context?.description ?? context?.setting ?? "");
  return (
    <ModalBackdrop onClose={onClose}>
      <form
        className="modal script-cast-context-dialog"
        role="dialog"
        aria-modal="true"
        aria-label="台本上のキャスト設定"
        onSubmit={(event) => {
          event.preventDefault();
          onSave({ role: role.trim(), description: description.trim() });
          onClose();
        }}
      >
        <DialogHeader eyebrow="SCRIPT CAST" title={`${character.name}の台本上の設定`} description="この台本だけでの役割と、読む人のための人物紹介です。キャスト一覧のプロフィールは変更しません。" />
        <div className="script-cast-context-identity" aria-hidden="true">
          <span className="script-cast-context-avatar">{character.avatarUrl ? <img src={avatarImageUrl(character.avatarUrl, character.avatarVersion)} alt="" /> : character.name.slice(0, 1)}</span>
          <div>
            <b>{character.name}</b>
          </div>
        </div>
        <div className="dialog-form-fields">
          <label className="dialog-form-field">
            役割
            <input value={role} maxLength={120} onChange={(event) => setRole(event.target.value)} />
          </label>
          <label className="dialog-form-field">
            人物紹介
            <textarea value={description} maxLength={600} onChange={(event) => setDescription(event.target.value)} />
          </label>
        </div>
        <DialogFooter>
          <button type="button" onClick={onClose}>
            キャンセル
          </button>
          <button type="submit" className="primary">
            保存
          </button>
        </DialogFooter>
      </form>
    </ModalBackdrop>
  );
}
