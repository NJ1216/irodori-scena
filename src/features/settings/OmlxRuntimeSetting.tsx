import { useState } from "react";
import { api } from "../../api";
import type { OmlxRuntime, OmlxRuntimeStatus } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { confirmDestructiveAction, useDestructiveConfirmation } from "../shared/destructiveConfirmation";
import { useSequentialPolling } from "../shared/useSequentialPolling";

function RuntimeRow({ item, onRefresh }: { item: OmlxRuntime; onRefresh: () => void }) {
  const key = `omlx-removal:${item.id}`;
  const confirming = useDestructiveConfirmation(key);
  const [message, setMessage] = useState("");
  const remove = async () => {
    if (!confirmDestructiveAction(key, setMessage, "この実行基盤をMacから削除します。", "削除")) return;
    try {
      await api.deleteOmlxRuntime(item.id);
      onRefresh();
    } catch (error) {
      setMessage((error as Error).message);
    }
  };
  return (
    <section className="llm-detail-section">
      <h3>
        {item.displayName} · {item.omlxVersion}
      </h3>
      <p className="subtle">
        {item.source === "scena" ? "SCENA構成" : item.source === "github-release" ? "公開リリース" : "既存環境"} · {(item.diskBytes / 1024 ** 3).toFixed(1)} GB
      </p>
      <p>{item.usedByModels?.map((model) => model.displayName).join("、") || "未使用"}</p>
      <p className="subtle">{item.deletionBlockedReason}</p>
      <button type="button" className={`danger${confirming ? " is-confirming" : ""}`} data-destructive-confirmation-key={key} disabled={!!item.deletionBlockedReason} onClick={() => void remove()}>
        {confirming ? "もう一度押して削除" : "実行基盤を削除"}
      </button>
      {message && (
        <p className="warning-text" role="alert">
          {message}
        </p>
      )}
    </section>
  );
}

export function OmlxRuntimeSetting({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={compact ? "settings-title-action" : "quiet-button"} onClick={() => setOpen(true)}>
        oMLX管理
      </button>
      {open && <RuntimeManager onClose={() => setOpen(false)} />}
    </>
  );
}

function RuntimeManager({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<OmlxRuntimeStatus | null>(null);
  const [message, setMessage] = useState("");
  const refresh = () =>
    void api
      .omlxRuntimes()
      .then(setStatus)
      .catch((error: Error) => setMessage(error.message));
  useSequentialPolling({ enabled: true, intervalMs: 2000, poll: api.omlxRuntimes, onResult: setStatus, onError: (error) => setMessage((error as Error).message), errorPolicy: "retry" });
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="omlx-management-title">
        <DialogHeader title="oMLX管理" titleId="omlx-management-title" description="実行基盤をモデル間で共有しています。使用する版はモデル詳細から変更できます。" />
        <div className="dialog-form-fields">
          {!status && <p>読み込んでいます…</p>}
          {status?.installedRuntimes.length === 0 && <p>導入済みの実行基盤はありません。</p>}
          {status?.installedRuntimes.map((item) => (
            <RuntimeRow key={item.id} item={item} onRefresh={refresh} />
          ))}
          {message && (
            <p className="warning-text" role="alert">
              {message}
            </p>
          )}
        </div>
        <DialogFooter>
          <button type="button" className="secondary" onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
