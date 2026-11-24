import { useEffect, useState } from "react";
import { api } from "../../api";
import type { LlmCard, OmlxRuntimeStatus } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { cachedOmlxReleases } from "./omlxReleaseCache";
import { isWindows } from "../shared/platform";
import { runtimeChoices, runtimeJobBusy, runtimeCurrentValue, type RuntimeChoice } from "./modelRuntimeChoices";

function InstallConfirmation({ choice, resumeModel, onClose, onConfirm }: { choice: RuntimeChoice; resumeModel: boolean; onClose: () => void; onConfirm: () => void }) {
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal llm-setting-dialog" role="dialog" aria-modal="true" aria-labelledby="runtime-install-title">
        <DialogHeader title={choice.installed ? "モデルの準備を再開しますか？" : `oMLX ${choice.version}を取得しますか？`} titleId="runtime-install-title" description="このモデルで動作を確認してから切り替えます。" />
        {resumeModel && <p className="subtle">モデルの取得も続きから再開します。</p>}
        {!choice.verified && <p className="warning-text">SCENA未検証の版です。依存ライブラリと使用容量が増える場合があります。</p>}
        <DialogFooter>
          <button type="button" className="secondary" onClick={onClose}>
            キャンセル
          </button>
          <button type="button" className="primary" onClick={onConfirm}>
            {choice.installed ? "再開" : "取得"}
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}

function BoundRuntimeOption({ card, choices }: { card: LlmCard; choices: RuntimeChoice[] }) {
  if (!card.runtimeId || card.runtime?.state === "ready") return null;
  const choice = choices.find((item) => item.value === card.runtimeId);
  return <option value={`bound:${card.runtimeId}`}>oMLX {choice?.version ?? card.runtime?.version ?? "登録済みの版"} · 準備が必要（設定済み）</option>;
}

export function ModelRuntimeSetting({ card, onRefresh }: { card: LlmCard; onRefresh: () => void }) {
  return isWindows() ? null : <OmlxModelRuntimeSetting card={card} onRefresh={onRefresh} />;
}

function OmlxModelRuntimeSetting({ card, onRefresh }: { card: LlmCard; onRefresh: () => void }) {
  const [status, setStatus] = useState<OmlxRuntimeStatus | null>(null);
  const [releases, setReleases] = useState<Array<{ tag: string }>>([]);
  const [confirmation, setConfirmation] = useState<RuntimeChoice | null>(null);
  const [error, setError] = useState("");
  const [catalogError, setCatalogError] = useState("");
  const [pending, setPending] = useState(false);
  const busy = runtimeJobBusy(card);
  const job = card.runtime?.job;
  const choices = runtimeChoices(card, status, releases);
  const current = runtimeCurrentValue(card);
  useEffect(() => {
    let alive = true;
    void api
      .omlxRuntimes()
      .then((value) => {
        if (alive) setStatus(value);
      })
      .catch((reason: Error) => {
        if (alive) setError(reason.message);
      });
    void cachedOmlxReleases()
      .then((value) => {
        if (alive) setReleases(value);
      })
      .catch(() => {
        if (alive) setCatalogError("公開版の一覧を取得できませんでした。");
      });
    return () => {
      alive = false;
    };
  }, []);
  const change = async (value: string) => {
    setConfirmation(null);
    setPending(true);
    setError("");
    try {
      await api.prepareModelRuntime(card.id, value.startsWith("release:") ? { tag: value.slice(8) } : { runtimeId: value });
      onRefresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setPending(false);
    }
  };
  const choose = (value: string) => {
    const choice = choices.find((item) => item.value === value);
    if (!choice || value === current) return;
    if (!choice.installed || card.runtime?.modelDownloadRequired) setConfirmation(choice);
    else void change(value);
  };
  const cancel = async () => {
    setPending(true);
    try {
      await api.cancelModelRuntime(card.id);
      onRefresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setPending(false);
    }
  };
  const progress = job && job.state !== "complete" ? job.message : "";
  return (
    <>
      <label className="dialog-form-field">
        実行基盤
        <select value={current} disabled={busy || pending} onChange={(event) => choose(event.target.value)}>
          <BoundRuntimeOption card={card} choices={choices} />
          {!current && (
            <option value="" disabled>
              {busy ? "準備中…" : "準備する版を選択"}
            </option>
          )}
          {choices.map((item) => (
            <option key={item.value} value={item.value}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      {progress && (
        <p className="subtle" role="status">
          {progress}
        </p>
      )}
      {busy && (
        <button type="button" className="quiet-button" disabled={pending} onClick={() => void cancel()}>
          取消
        </button>
      )}
      {error && (
        <p className="warning-text" role="alert">
          {error}
        </p>
      )}
      {catalogError && <p className="subtle">{catalogError}</p>}
      {confirmation && <InstallConfirmation resumeModel={!!card.runtime?.modelDownloadRequired} choice={confirmation} onClose={() => setConfirmation(null)} onConfirm={() => void change(confirmation.value)} />}
    </>
  );
}
