import { useEffect, useState } from "react";
import { api } from "../../api";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { confirmDestructiveAction, useDestructiveConfirmation } from "../shared/destructiveConfirmation";

type Status = Awaited<ReturnType<typeof api.llamaCppRuntime>>;

function RuntimeRow({ status, onDeleted }: { status: Status; onDeleted: () => void }) {
  const key = `llama-cpp-removal:${status.backend}`;
  const confirming = useDestructiveConfirmation(key);
  const [message, setMessage] = useState("");
  const remove = async () => {
    if (!confirmDestructiveAction(key, setMessage, "この実行基盤をPCから削除します。", "削除")) return;
    try {
      await api.deleteLlamaCppRuntime(status.backend);
      onDeleted();
    } catch (error) {
      setMessage((error as Error).message);
    }
  };
  return (
    <section className="llm-detail-section">
      <h3>
        llama.cpp {status.version} · {status.backend === "cuda" ? "NVIDIA CUDA" : "CPU"}
      </h3>
      <p className="subtle">内蔵LLMモデルの追加時にSCENAが自動で導入します。</p>
      <button type="button" className={`danger${confirming ? " is-confirming" : ""}`} data-destructive-confirmation-key={key} onClick={() => void remove()}>
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

export function LlamaCppRuntimeSetting({ compact = false }: { compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" className={compact ? "settings-title-action" : "quiet-button"} onClick={() => setOpen(true)}>
        llama.cpp管理
      </button>
      {open && <RuntimeManager onClose={() => setOpen(false)} />}
    </>
  );
}

function RuntimeManager({ onClose }: { onClose: () => void }) {
  const [items, setItems] = useState<Status[] | null>(null);
  const [backend, setBackend] = useState<"cuda" | "cpu">("cuda");
  const [message, setMessage] = useState("");
  const refresh = () =>
    void Promise.all([api.llamaCppRuntime(), api.llamaCppRuntime("cuda"), api.llamaCppRuntime("cpu")])
      .then(([selected, ...values]) => {
        setBackend(selected.backend);
        setItems(values.filter((item) => item.ready));
      })
      .catch((error: Error) => setMessage(error.message));
  const select = async (next: "cuda" | "cpu") => {
    setMessage("");
    try {
      const selected = await api.selectLlamaCppRuntime(next);
      setBackend(selected.backend);
    } catch (error) {
      setMessage((error as Error).message);
    }
  };
  useEffect(refresh, []);
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="llama-management-title">
        <DialogHeader title="llama.cpp管理" titleId="llama-management-title" description="実行基盤はモデル追加時に自動で導入されます。削除するには、先に内蔵LLMモデルをすべて削除してください。" />
        <div className="dialog-form-fields">
          <label className="dialog-form-field">
            使用する実行基盤
            <select value={backend} onChange={(event) => void select(event.target.value as "cuda" | "cpu")}>
              <option value="cuda">NVIDIA CUDA（推奨）</option>
              <option value="cpu">CPU</option>
            </select>
            <small>次に内蔵LLMモデルを追加するとき、この実行基盤を自動で導入します。</small>
          </label>
          {!items && <p>読み込んでいます…</p>}
          {items?.length === 0 && <p>導入済みの実行基盤はありません。</p>}
          {items?.map((item) => (
            <RuntimeRow key={item.backend} status={item} onDeleted={refresh} />
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
