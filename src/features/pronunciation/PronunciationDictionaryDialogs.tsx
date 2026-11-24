import type { PronunciationDictionaryEntry } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";

export function ScopeRemovalDialog({ removal, onClose, onRemove }: { removal: { entry: PronunciationDictionaryEntry; scope: "global" | "project" }; onClose: () => void; onRemove: () => Promise<void> }) {
  const destination = removal.scope === "global" ? "SCENA" : "PROJECT";
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal pronunciation-regeneration-dialog" role="dialog" aria-modal="true" aria-labelledby="pronunciation-scope-removal-title">
        <DialogHeader eyebrow="PRONUNCIATION" titleId="pronunciation-scope-removal-title" title={`${destination}から「${removal.entry.term}」を削除しますか？`} description="この保存先から読みを削除します。削除後も履歴から元に戻せます。" />
        <DialogFooter>
          <button type="button" onClick={onClose}>
            キャンセル
          </button>
          <button type="button" className="danger" onClick={() => void onRemove()}>
            {destination}から削除
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

export function ScopeConflictDialog({ conflict, onClose, onReplace }: { conflict: { entry: PronunciationDictionaryEntry; scope: "global" | "project" }; onClose: () => void; onReplace: () => Promise<void> }) {
  const destination = conflict.scope === "global" ? "SCENA" : "PROJECT";
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal pronunciation-regeneration-dialog" role="dialog" aria-modal="true" aria-labelledby="pronunciation-scope-conflict-title">
        <DialogHeader eyebrow="PRONUNCIATION" titleId="pronunciation-scope-conflict-title" title={`${destination}の「${conflict.entry.term}」を置き換えますか？`} description="同じ語句の異なる版があります。置き換えると、この行の内容で一つに統合されます。" />
        <DialogFooter>
          <button type="button" onClick={onClose}>
            キャンセル
          </button>
          <button type="button" className="primary" onClick={() => void onReplace()}>
            置き換える
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

export function RegenerationDialog({ ids, mode, onMode, onClose, onRegenerate }: { ids: string[]; mode: "append" | "replace"; onMode: (mode: "append" | "replace") => void; onClose: () => void; onRegenerate: (ids: string[], mode: "append" | "replace") => Promise<void> }) {
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal pronunciation-regeneration-dialog" role="dialog" aria-modal="true" aria-labelledby="pronunciation-regeneration-title">
        <DialogHeader eyebrow="PRONUNCIATION" titleId="pronunciation-regeneration-title" title={`辞書の変更により${ids.length}行の読みが変わります`} description="辞書の変更はすでに保存されています。影響する生成済みの発話を再生成しますか？" />
        <div className="choice-group pronunciation-regeneration-options" role="radiogroup" aria-label="再生成方法">
          <label className="choice-option">
            <input type="radio" name="dictionary-regeneration-mode" checked={mode === "append"} onChange={() => onMode("append")} />
            <span>新規テイクとして追加（推奨）</span>
          </label>
          <label className="choice-option">
            <input type="radio" name="dictionary-regeneration-mode" checked={mode === "replace"} onChange={() => onMode("replace")} />
            <span>選択テイクを上書き</span>
          </label>
        </div>
        <DialogFooter>
          <button type="button" onClick={onClose}>
            再生成しない
          </button>
          <button
            type="button"
            className="primary"
            onClick={() => {
              onClose();
              void onRegenerate(ids, mode);
            }}
          >
            再生成する
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
