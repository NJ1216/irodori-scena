import type { LoraInputRow } from "../../types/lora";
import type { LoraTrainingModel } from "./LoraTrainingView";
import { inputIssues, inputLabel, inputNeedsReview, inputStatus } from "./loraInputStatus";
import type { useLoraInputPlayback } from "./useLoraInputPlayback";

type Props = { row: LoraInputRow; model: LoraTrainingModel; expanded: boolean; onExpand: () => void; playback: ReturnType<typeof useLoraInputPlayback> };
export function LoraInputTableRow({ row, model, expanded, onExpand, playback }: Props) {
  const label = inputLabel(row);
  const excluded = model.excluded.has(row.id);
  return (
    <>
      <tr className={expanded ? "lora-input-selected" : ""}>
        <td>
          <button type="button" className="dictionary-cell-button" title={label} aria-label={`${label}を確認`} aria-expanded={expanded} onClick={onExpand}>
            {label}
          </button>
        </td>
        <td>
          <button type="button" className="dictionary-cell-button" aria-label={`${label}の台詞を編集`} aria-expanded={expanded} onClick={onExpand}>
            {row.text.trim() ? row.text.replace(/[\r\n]+/g, " ") : <em>台詞を入力してください</em>}
          </button>
        </td>
        <td>
          <div className="lora-input-audio">
            <div className="audio-playback-bar is-compact">
              <button type="button" disabled={!row.audioUrl} title={!row.audioUrl ? "試聴するにはフォルダを取り込み直してください。" : undefined} aria-label={`${label}を${playback.activeId === row.id ? "停止" : "再生"}`} onClick={() => void playback.toggle(row)}>
                {playback.activeId === row.id ? (playback.playing ? "■" : "…") : "▶"}
              </button>
            </div>
            {row.durationSeconds != null && <span className="type-small">{row.durationSeconds.toFixed(1)}秒</span>}
          </div>
        </td>
        <td>
          <span className={!excluded && inputNeedsReview(row) ? "warning-text" : "subtle"} title={inputIssues(row).join(" / ")}>
            {inputStatus(row, excluded)}
          </span>
        </td>
        <td>
          <span className="choice-option">
            <input type="checkbox" aria-label={`${label}を除外`} checked={excluded} onChange={() => model.toggleExcluded(row.id)} />
          </span>
        </td>
      </tr>
      {expanded && (
        <tr className="lora-input-edit-row">
          <td colSpan={5}>
            <LoraInputEditor row={row} model={model} excluded={excluded} />
          </td>
        </tr>
      )}
    </>
  );
}
function LoraInputEditor({ row, model, excluded }: { row: LoraInputRow; model: LoraTrainingModel; excluded: boolean }) {
  return (
    <div className="lora-input-editor">
      <p className="subtle">{row.textName ?? "台詞ファイルなし：本文を手入力できます。"}</p>
      {inputIssues(row).map((issue) => (
        <p role="alert" className="warning-text" key={issue}>
          {issue}
        </p>
      ))}
      {row.blocked && <p className="warning-text">対応を特定できません。フォルダ内のファイルを確認して取り込み直すか、この素材を除外してください。</p>}
      <label className="dialog-form-field">
        台詞
        <textarea aria-label="台詞" value={row.text} disabled={excluded || row.blocked} onChange={(event) => model.updateRow(row.id, { text: event.target.value })} />
      </label>
      <details>
        <summary>声・話し方の説明（任意）</summary>
        <label className="dialog-form-field">
          声・話し方の説明
          <textarea aria-label="声・話し方の説明" value={row.caption} disabled={excluded || row.blocked} onChange={(event) => model.updateRow(row.id, { caption: event.target.value })} />
        </label>
      </details>
    </div>
  );
}
