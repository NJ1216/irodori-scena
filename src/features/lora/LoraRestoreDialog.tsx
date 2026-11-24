import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { loraApi } from "../../api-lora";
import type { LoraAsset } from "../../types/lora";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { useLoraDialogAction } from "./loraDialogActionHook";
import { useLoraRegisterFocus } from "./useLoraRegisterFocus";

export function LoraRestoreDialog({ onRestored, onClose }: { onRestored: (asset: LoraAsset) => void; onClose: () => void }) {
  const [assets, setAssets] = useState<LoraAsset[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [message, setMessage] = useState("");
  const { busy, error, perform } = useLoraDialogAction();
  const ref = useLoraRegisterFocus(busy, false, '[aria-label="登録済みLoRA"]');
  useEffect(() => {
    let active = true;
    void loraApi
      .archivedAdapters()
      .then((items) => {
        if (active) {
          setAssets(items);
          setLoaded(true);
        }
      })
      .catch((cause) => {
        if (active) setLoadError(String(cause));
      });
    return () => {
      active = false;
    };
  }, []);
  function restore(asset: LoraAsset) {
    void perform(async () => {
      const restored = await loraApi.restoreAdapter(asset.id);
      setAssets((items) => items.filter((item) => item.id !== asset.id));
      onRestored(restored);
      setMessage(`「${asset.name}」を戻しました。キャストの選択欄から選べます。`);
    });
  }
  return createPortal(
    <ModalBackdrop onClose={onClose} disabled={busy}>
      <form
        ref={ref}
        tabIndex={-1}
        className="modal lora-restore-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="lora-restore-title"
        onSubmit={(event) => {
          event.preventDefault();
          event.stopPropagation();
        }}
      >
        <DialogHeader titleId="lora-restore-title" title="登録解除したLoRAを戻す" description="登録を戻すと、配合への追加候補に表示されます。" />
        {!loaded && !loadError && <p role="status">確認中…</p>}
        {loaded && !assets.length && <p className="muted">登録解除したLoRAはありません。</p>}
        <div className="lora-asset-list">
          {assets.map((asset) => (
            <div className="lora-asset-row" key={asset.id}>
              <span>{asset.name}</span>
              <button type="button" className="secondary" disabled={busy} aria-label={`${asset.name}を戻す`} onClick={() => restore(asset)}>
                戻す
              </button>
            </div>
          ))}
        </div>
        {(error || loadError) && (
          <p role="alert" className="warning-text">
            {error || loadError}
          </p>
        )}
        {message && <p role="status">{message}</p>}
        <DialogFooter>
          <button type="button" className="secondary" disabled={busy} onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
      </form>
    </ModalBackdrop>,
    document.body,
  );
}
