import { useState } from "react";
import { createPortal } from "react-dom";
import type { LoraMix } from "../../types/project";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { addMixEntry } from "./loraMix";
import { useLoraRegisterFocus } from "./useLoraRegisterFocus";
import type { useMixLibrary } from "./useMixLibrary";
type Props = { library: ReturnType<typeof useMixLibrary>; mix: LoraMix; onChange: (mix: LoraMix) => void };
export function MixLibraryActions(props: Props) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className="voice-action-button" disabled={props.mix.entries.length >= 4 || !props.library.loaded} onClick={() => setOpen(true)}>
        LoRAを追加
      </button>
      {open && <MixAddDialog {...props} onClose={() => setOpen(false)} />}
    </>
  );
}
function MixAddDialog({ library, mix, onChange, onClose }: Props & { onClose: () => void }) {
  const { assets, selectedId, setSelectedId, selected, runtime } = library;
  const ref = useLoraRegisterFocus(false, false);
  const available = assets.filter((asset) => !asset.archived && asset.baseModelRepo === runtime?.baseModelRepo && asset.baseModelRevision === runtime?.baseModelRevision);
  const canAdd = available.some((asset) => asset.id === selectedId) && mix.entries.length < 4 && !mix.entries.some((entry) => entry.assetId === selectedId);
  return (
    <>
      {createPortal(
        <ModalBackdrop onClose={onClose}>
          <form
            ref={ref}
            className="modal lora-register-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="mix-add-title"
            onSubmit={(event) => {
              event.preventDefault();
              event.stopPropagation();
              if (!canAdd || !selected) return;
              onChange(addMixEntry(mix, { assetId: selected.id, adapterHash: selected.adapterHash, baseModelRepo: selected.baseModelRepo, baseModelRevision: selected.baseModelRevision }));
              onClose();
            }}
          >
            <DialogHeader titleId="mix-add-title" title="LoRAを追加" />
            <label className="dialog-form-field">
              登録済みLoRA
              <select
                aria-label="登録済みLoRA"
                value={selectedId}

                onChange={(event) => {
                  setSelectedId(event.target.value);
                }}
              >
                <option value="">LoRAを選択</option>
                {available.map((asset) => (
                  <option key={asset.id} value={asset.id}>
                    {asset.name}
                  </option>
                ))}
              </select>
            </label>
            <DialogFooter>
              <button type="button" className="secondary" onClick={onClose}>
                キャンセル
              </button>
              <button type="submit" className="primary" disabled={!canAdd}>
                追加
              </button>
            </DialogFooter>
          </form>
        </ModalBackdrop>,
        document.body,
      )}
    </>
  );
}
