import type { DraftJob, LlmUsageClassification } from "../../types";
import { DialogFooter, DialogHeader, ModalBackdrop } from "../shared/overlays";
import { formatDuration } from "../shared/studio-utils";

const number = new Intl.NumberFormat("ja-JP");
const accuracy = (value?: LlmUsageClassification) => (value === "reported" ? "実測" : value === "partial" ? "一部概算" : "概算");

// JSX conditionals mirror optional fields in the wire-compatible summary.
// eslint-disable-next-line complexity
export function DraftCompletionDialog({ job, onClose }: { job: DraftJob; onClose: () => void }) {
  const usage = job.tokenUsage;
  const elapsed = job.completedAt ? Math.max(0, job.completedAt - job.startedAt) / 1000 : 0;
  const fallbackTotal = job.tokenUsageAvailable ? job.usedTokens : null;
  const title = job.title || "無題の台本";
  const provider = job.provider === "scena-local" ? "SCENA" : job.provider || "不明";
  const model = job.model || "不明";
  const input = usage ? number.format(usage.inputTokens) : "未取得";
  const output = usage ? number.format(usage.outputTokens) : "未取得";
  const total = usage || fallbackTotal !== null ? number.format(usage?.totalTokens ?? fallbackTotal ?? 0) : "未取得";
  const usageLabel = usage?.unknownUsageCalls ? "取得できた使用量のみ表示" : usage ? accuracy(job.tokenUsageClassification) : fallbackTotal === null ? "使用量を取得できませんでした" : "実測";
  return (
    <ModalBackdrop onClose={onClose}>
      <section className="modal draft-completion-dialog" role="dialog" aria-modal="true" aria-label="AI台本の生成完了">
        <DialogHeader eyebrow="AI SCRIPT RESULT" title="AI台本の生成結果" />
        <div className="draft-completion-body">
          <h3>{title}</h3>
          <h4>生成結果</h4>
          <dl className="draft-completion-list">
            <div>
              <dt>発話行</dt>
              <dd>{number.format(job.appendedLines)} 行</dd>
            </div>
            <div>
              <dt>同時発話</dt>
              <dd>{number.format(job.appendedCueCount ?? 0)} 組</dd>
            </div>
            <div>
              <dt>推定尺</dt>
              <dd>{formatDuration(job.estimatedSeconds)}</dd>
            </div>
            <div>
              <dt>指定時間</dt>
              <dd>{formatDuration(job.targetMinutes !== undefined ? job.targetMinutes * 60 : job.targetCharacters / 5.5)}</dd>
            </div>
            <div>
              <dt>生成場面</dt>
              <dd>{number.format(job.generatedSceneCount ?? job.completedDevelopments ?? job.completedChunks ?? 0)} 場面</dd>
            </div>
            <div>
              <dt>部分継続</dt>
              <dd>{job.partialContinuationUsed ? "あり" : "なし"}</dd>
            </div>
            <div>
              <dt>生成所要時間</dt>
              <dd>{formatDuration(elapsed)}</dd>
            </div>
          </dl>
          <h4>使用モデル・通信</h4>
          <dl className="draft-completion-list">
            <div>
              <dt>接続方式</dt>
              <dd>{provider}</dd>
            </div>
            <div>
              <dt>モデル</dt>
              <dd>{model}</dd>
            </div>
            <div>
              <dt>生成処理（再試行を除く）</dt>
              <dd>{number.format(job.llmCallCount)} 回</dd>
            </div>
            <div>
              <dt>HTTP通信（再試行を含む）</dt>
              <dd>{job.transportCallCount === undefined ? "未取得" : `${number.format(job.transportCallCount)} 回`}</dd>
            </div>
          </dl>
          <h4>トークン使用量</h4>
          <dl className="draft-completion-list">
            <div>
              <dt>入力token{usage?.inputEstimated ? "（概算を含む）" : ""}</dt>
              <dd>{input}</dd>
            </div>
            <div>
              <dt>出力token{usage?.outputEstimated ? "（概算を含む）" : ""}</dt>
              <dd>{output}</dd>
            </div>
            <div>
              <dt>合計token</dt>
              <dd>{total}</dd>
            </div>
            <div>
              <dt>キャッシュ入力token</dt>
              <dd>{!usage || usage.cachedInputEstimated ? "未取得" : number.format(usage.cachedInputTokens)}</dd>
            </div>
            <div>
              <dt>数値の確かさ</dt>
              <dd>{usageLabel}</dd>
            </div>
          </dl>
          <details className="draft-completion-notes">
            <summary>使用量の補足</summary>
            <p className="subtle">未取得は0を意味しません。キャッシュ入力は入力の内数です。入力・出力は概算を含む場合があり、請求額を示すものではありません。</p>
            {Boolean(usage?.unknownUsageCalls) && <p className="subtle">使用量を取得できなかった生成が {usage?.unknownUsageCalls} 回あります。その分は合計に含めていません。請求額を示す数値ではありません。</p>}
            {Boolean(usage?.unconfirmedInputTokens) && <p className="subtle">使用量不明の生成に対する入力見積もり：{number.format(usage?.unconfirmedInputTokens ?? 0)} token。実消費量ではないため、上の入力・合計には加算していません。</p>}
            {Boolean(usage?.unattributedTokens) && <p className="subtle">合計には、入力・出力の内訳に含まれない {number.format(usage?.unattributedTokens ?? 0)} token（内部思考など、内訳未確認）も含まれます。</p>}
          </details>
        </div>
        <DialogFooter>
          <button type="button" onClick={onClose}>
            閉じる
          </button>
        </DialogFooter>
      </section>
    </ModalBackdrop>
  );
}
