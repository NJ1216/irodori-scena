import { useState } from "react";
import { api } from "../../api";
import type { LlmCard, LlmTestJob } from "../../types";
import { isWindows } from "../shared/platform";
import { WindowsModelRuntimeSetting } from "./WindowsModelRuntimeSetting";
import { useSequentialPolling } from "../shared/useSequentialPolling";

const terminal = (state: LlmTestJob["state"]) => ["passed", "failed", "cancelled"].includes(state);

type Props = { card?: LlmCard; cardId: string; disabled?: boolean; onStatus: (value: string, state: "passed" | "failed" | "testing") => void; onComplete: () => void };
export function LlmCardTestControls(props: Props) {
  if (isWindows() && props.card && props.card.source !== "remote") return <WindowsModelRuntimeSetting card={props.card} onRefresh={props.onComplete} />;
  return <RemoteTestControls {...props} />;
}

function RemoteTestControls({ cardId, onStatus, onComplete, disabled = false }: Props) {
  const [job, setJob] = useState<LlmTestJob | null>(null);
  const [cancelling, setCancelling] = useState(false);
  useSequentialPolling({
    enabled: !!job && !terminal(job.state),
    intervalMs: 500,
    initialDelayMs: 500,
    poll: () => api.llmCardTest(job!.id),
    terminal: (next) => terminal(next.state),
    onResult: (next) => {
      setJob(next);
      if (!terminal(next.state)) return;
      onStatus(next.state === "passed" ? "接続でき、モデルの使用に問題がないことを確認しました。" : next.state === "cancelled" ? "動作確認を終了しました。" : `接続またはモデルの使用に問題があります（${next.errorCategory}）: ${next.error ?? ""}`, next.state === "passed" ? "passed" : "failed");
      onComplete();
    },
    onError: (error) => onStatus(`動作確認の状態を取得できませんでした: ${(error as Error).message}`, "failed"),
  });
  const testing = Boolean(job && !terminal(job.state));
  return (
    <div className="model-tools">
      <button
        type="button"
        className="secondary settings-inline-action"
        disabled={cancelling || (!testing && disabled)}
        onClick={() => {
          if (testing && job) {
            setCancelling(true);
            void api
              .cancelLlmCardTest(job.id)
              .then(setJob)
              .catch((error) => onStatus(`取消を要求できませんでした: ${(error as Error).message}`, "failed"))
              .finally(() => setCancelling(false));
            return;
          }
          onStatus("接続とモデルの基本動作を確認しています…", "testing");
          void api
            .startLlmCardTest(cardId)
            .then(setJob)
            .catch((error) => onStatus(`動作確認を開始できませんでした: ${(error as Error).message}`, "failed"));
        }}
      >
        {cancelling ? "取消要求中…" : testing ? "確認を取り消す" : "基本動作を確認"}
      </button>
    </div>
  );
}
