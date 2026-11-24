import { useState } from "react";
import { api } from "../../api";
import type { LlmCard } from "../../types";
import { runtimeJobBusy } from "./modelRuntimeChoices";

export function WindowsModelRuntimeSetting({ card, onRefresh }: { card: LlmCard; onRefresh: () => void }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const busy = runtimeJobBusy(card);
  const run = async () => {
    setPending(true);
    setError("");
    try {
      if (busy) await api.cancelModelRuntime(card.id);
      else await api.prepareModelRuntime(card.id, {});
      onRefresh();
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setPending(false);
    }
  };
  return (
    <div className="dialog-form-field">
      {card.runtime?.job?.message && (
        <p className="subtle" role="status">
          {card.runtime.job.message}
        </p>
      )}
      {busy && <p className="subtle">準備と基本動作の確認が終わるまでお待ちください。</p>}
      <button type="button" className="secondary settings-inline-action" disabled={pending} onClick={() => void run()}>
        {pending ? (busy ? "取消要求中…" : "確認開始中…") : busy ? "確認を取り消す" : "基本動作を確認"}
      </button>
      {error && (
        <p className="warning-text" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
