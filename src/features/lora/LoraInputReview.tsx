import { useState } from "react";
import type { LoraTrainingModel } from "./LoraTrainingView";
import { LoraInputTableRow } from "./LoraInputTableRow";
import { inputNeedsReview } from "./loraInputStatus";
import { useLoraInputPlayback } from "./useLoraInputPlayback";

export function LoraInputReview({ model }: { model: LoraTrainingModel }) {
  const [expandedId, setExpandedId] = useState("");
  const playback = useLoraInputPlayback();
  const included = model.rows.filter((row) => !model.excluded.has(row.id));
  const problems = included.filter(inputNeedsReview).length;
  return (
    <>
      <div className="lora-review-intro">
        <p className="subtle">音声と台詞を確認してください。行を選ぶと全文を編集できます。対応しない素材は、本文を入力するか明示的に除外します。</p>
        <p className="type-small">
          {model.folderName && <>{model.folderName} / </>}
          {model.rows.length}件・学習対象 {included.length}件・要確認 {problems}件
        </p>
        {!!model.ignoredTextCount && <p className="subtle">対応する音声のないTXT {model.ignoredTextCount}件は取り込み対象外です。</p>}
      </div>
      <LoraBulkCaption model={model} />
      <div className="dictionary-table-wrap lora-input-scroll" role="region" aria-label="学習素材一覧" tabIndex={0}>
        <table className="dictionary-table lora-input-table">
          <colgroup>
            <col className="lora-input-file-column" />
            <col className="lora-input-text-column" />
            <col className="lora-input-audio-column" />
            <col className="lora-input-status-column" />
            <col className="lora-input-exclude-column" />
          </colgroup>
          <thead>
            <tr>
              <th scope="col">ファイル</th>
              <th scope="col">台詞</th>
              <th scope="col">再生</th>
              <th scope="col">状態</th>
              <th scope="col">除外</th>
            </tr>
          </thead>
          <tbody>
            {model.rows.map((row) => (
              <LoraInputTableRow key={row.id} row={row} model={model} playback={playback} expanded={expandedId === row.id} onExpand={() => setExpandedId(expandedId === row.id ? "" : row.id)} />
            ))}
          </tbody>
        </table>
      </div>
      {playback.error && (
        <p role="alert" className="warning-text">
          {playback.error}
        </p>
      )}
    </>
  );
}
function LoraBulkCaption({ model }: { model: LoraTrainingModel }) {
  return (
    <details>
      <summary>声・話し方の説明を追加（任意）</summary>
      <label className="dialog-form-field">
        共通の説明
        <textarea value={model.caption} onChange={(event) => model.setCaption(event.target.value)} placeholder="声の個性、話し方、状況など" />
      </label>
      <button type="button" className="secondary" onClick={model.bulkCaption}>
        全素材に適用
      </button>
      <p className="subtle">空欄でも学習できます。音声の条件を説明するもので、感情だけを取り出す指示ではありません。素材ごとの説明は行を選んで修正できます。</p>
    </details>
  );
}
