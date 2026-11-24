import { useEffect, useState } from "react";
import { loraApi } from "../../api-lora";
import type { LoraAsset } from "../../types/lora";
import { LoraLibraryToolbar } from "./LoraLibraryToolbar";
import { LoraManagementBack } from "./LoraManagementBack";
import { StepHeading } from "../shared/StepHeading";
import { LoraAssetEditDialog } from "./LoraAssetEditDialog";
import { LoraRegisterDialog } from "./LoraRegisterDialog";
import { LoraRestoreDialog } from "./LoraRestoreDialog";
import { useLoraDeletion } from "./loraDeletionHook";

export function LoraLibraryPanel({ onBack, onContinue }: { onBack: () => void; onContinue: (asset: LoraAsset) => void }) {
  const [assets, setAssets] = useState<LoraAsset[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [selectedId, setSelectedId] = useState("");
  const [register, setRegister] = useState(false);
  const [editing, setEditing] = useState<LoraAsset | null>(null);
  const [restore, setRestore] = useState(false);
  useEffect(() => {
    let active = true;
    void loraApi
      .adapters(true)
      .then((items) => {
        if (active) {
          setAssets(items);
          setLoaded(true);
        }
      })
      .catch((cause) => {
        if (active) setError(String(cause));
      });
    return () => {
      active = false;
    };
  }, []);
  const selected = assets.find((asset) => asset.id === selectedId && !asset.archived);
  function upsert(asset: LoraAsset) {
    setAssets((items) => [...items.filter((item) => item.id !== asset.id), asset]);
  }
  const deletion = useLoraDeletion({
    selected,
    onDeleted: (asset) => {
      setAssets((items) => items.filter((item) => item.id !== asset.id));
      setSelectedId("");
    },
  });
  const registered = assets.filter((asset) => !asset.archived);
  return (
    <>
      <LoraManagementBack onBack={onBack} disabled={deletion.busy} />
      <section className="panel lora-composer">
        <StepHeading number={1}>登録済みLoRAを管理する</StepHeading>
        <LibraryNotices loaded={loaded} empty={!registered.length} error={error || deletion.error} memo={selected?.memo} />
        {registered.length > 0 && (
          <label className="dialog-form-field">
            登録済みLoRA
            <select
              aria-label="登録済みLoRA"
              value={selectedId}
              disabled={deletion.busy}
              onChange={(event) => {
                deletion.cancel();
                setSelectedId(event.target.value);
              }}
            >
              <option value="">LoRAを選択</option>
              {registered.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.name}
                </option>
              ))}
            </select>
          </label>
        )}
        <LoraLibraryToolbar
          canManage={Boolean(selected)}
          busy={deletion.busy}
          pending={deletion.pending}
          confirmationKey={deletion.key}
          onEdit={() => selected && setEditing(selected)}
          onContinue={() => selected && onContinue(selected)}
          onRegister={() => setRegister(true)}
          onDelete={() => void deletion.requestDelete()}
        />
        {assets.some((asset) => asset.archived) && (
          <button type="button" className="link-button" disabled={deletion.busy} onClick={() => setRestore(true)}>
            登録を戻す
          </button>
        )}
        {editing && <LoraAssetEditDialog asset={editing} onSaved={upsert} onClose={() => setEditing(null)} />}
        {register && <LoraRegisterDialog onClose={() => setRegister(false)} onRegistered={upsert} />}
        {restore && <LoraRestoreDialog onClose={() => setRestore(false)} onRestored={upsert} />}
      </section>
    </>
  );
}

function LibraryNotices({ loaded, empty, error, memo }: { loaded: boolean; empty: boolean; error: string; memo?: string }) {
  return (
    <>
      {!loaded && !error && <p role="status">読み込んでいます…</p>}
      {loaded && empty && <p className="subtle">登録済みのLoRAはありません。</p>}
      {memo && <p className="subtle">{memo}</p>}
      {error && (
        <p role="alert" className="warning-box">
          {error}
        </p>
      )}
    </>
  );
}
