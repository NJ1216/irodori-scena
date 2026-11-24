import { useState } from "react";
import type { DialogueLine, Take } from "../../types";
import { formatTakeSeconds } from "../shared/studio-utils";
import { LineStatusIcon } from "./LineStatusIcon";
import { downloadWav } from "../shared/studio-utils";
import { TakeDownloadIcon } from "./TakeDownloadIcon";
import { ttsModelLabel } from "./ttsModelLabel";
import { takeSamplingPresentation } from "../shared/ttsSampling";

export function LineTakePicker({
  line,
  downloadFileName,
  busy,
  defaultSpeechRate,
  onNotice,
  onDeleteTake,
  onSelectTake,
}: {
  line: DialogueLine;
  downloadFileName: string;
  busy: boolean;
  defaultSpeechRate: number;
  onNotice: (message: string) => void;
  onDeleteTake: (take: Take) => Promise<void>;
  onSelectTake: (takeId: string) => void;
}) {
  const [confirmDeleteTakeId, setConfirmDeleteTakeId] = useState<string | null>(null);
  // Older AI-direction results use an empty string to mean "use the shared
  // rate". Treat every non-numeric persisted value the same way so a legacy
  // project cannot prevent the whole studio from rendering.
  const rawSpeechRate: unknown = line.speechRate;
  const savedSpeechRate = typeof rawSpeechRate === "string" && !rawSpeechRate.trim() ? Number.NaN : Number(rawSpeechRate);
  const displaySpeechRate = Number.isFinite(savedSpeechRate) ? savedSpeechRate : Number(defaultSpeechRate);
  if (!line.takes.length) return null;
  return (
    <div className="take-picker">
      {line.takes.map((item, index) => {
        const confirming = confirmDeleteTakeId === item.id;
        const modelLabel = ttsModelLabel(item.ttsConfiguration?.modelRevision);
        const sampling = takeSamplingPresentation(item);
        return (
          <span className={`take-choice ${confirming ? "is-confirming" : ""}`} key={item.id} onMouseLeave={() => !busy && setConfirmDeleteTakeId(null)}>
            <button
              className={item.id === line.selectedTakeId ? "selected" : ""}
              aria-describedby={`${item.id}-summary`}
              onClick={() => {
                setConfirmDeleteTakeId(null);
                onSelectTake(item.id);
              }}
            >
              Take {index + 1}
            </button>
            <span className="take-tooltip" id={`${item.id}-summary`} role="tooltip">
              <span className="take-tooltip-details">
                <span className="line-meta-item">
                  <LineStatusIcon name="seed" tooltip="Seed" />
                  {item.seed}
                </span>
                <span className="line-meta-item">
                  <LineStatusIcon name="rate" tooltip="話速" />
                  {displaySpeechRate.toFixed(2)}
                </span>
                <span className="line-meta-item" aria-label={`音声の長さ ${formatTakeSeconds(item.durationSeconds)}`}>
                  <LineStatusIcon name="audio" tooltip="音声の長さ" />
                  {formatTakeSeconds(item.durationSeconds)}
                </span>
                <span className={`quality-pill ${sampling.className}`}>{sampling.label}</span>
              </span>
              {modelLabel && (
                <span className="take-model-tag" title={`音声モデル: Irodori-TTS ${modelLabel}`}>
                  {modelLabel}
                </span>
              )}
              <button
                className="take-tooltip-save"
                type="button"
                title="WAVを保存"
                aria-label="このテイクのWAVを保存"
                onClick={(event) => {
                  event.stopPropagation();
                  void downloadWav(item.audioUrl, downloadFileName)
                    .then((savedName) => onNotice(savedName ? `「${savedName}」をダウンロードフォルダに保存しました。` : "WAVをダウンロードしました。"))
                    .catch((error: Error) => onNotice(`WAVを保存できませんでした: ${error.message}`));
                }}
              >
                <TakeDownloadIcon />
              </button>
            </span>
            <button
              className="delete-take"
              title={confirming ? `Take ${index + 1} を削除する` : `Take ${index + 1} を削除`}
              aria-label={confirming ? `Take ${index + 1} の削除を確定` : `Take ${index + 1} を削除`}
              disabled={busy}
              onClick={(event) => {
                event.stopPropagation();
                if (confirming) {
                  setConfirmDeleteTakeId(null);
                  void onDeleteTake(item);
                } else setConfirmDeleteTakeId(item.id);
              }}
            >
              {confirming ? "✓" : "×"}
            </button>
          </span>
        );
      })}
    </div>
  );
}
