import type { LlmSessionOperation, LlmSessionUsage, LlmTokenUsage, LlmUsageClassification } from "../../types";

const format = (value: number) => value.toLocaleString("ja-JP");
const accuracy = (value?: LlmUsageClassification) => (value === "reported" ? "実測" : value === "partial" ? "一部概算" : "概算");
// Providers such as Ollama do not report cache reuse; an unreported zero is shown as unknown, not as no reuse.
const cached = (value?: LlmTokenUsage) => (!value || (value.cachedInputEstimated && !value.cachedInputTokens) ? "不明" : format(value.cachedInputTokens));
const status = (value: LlmSessionOperation["status"]) => (value === "running" ? "処理中" : value === "completed" ? "成功" : value === "cancelled" ? "キャンセル" : "失敗");

export function TokenUsageMenu({ usage, onReset }: { usage: LlmSessionUsage | null; onReset: () => void }) {
  const total = usage?.total;
  return (
    <div className="main-window-footer-item main-window-token-menu">
      <button type="button" aria-label="セッションtoken使用量">
        token {format(total?.totalTokens ?? 0)}
      </button>
      <section className="main-window-footer-submenu main-window-token-submenu" aria-label="セッションtoken使用量メニュー">
        <header>
          <strong>セッションtoken</strong>
          <span>
            <small>{accuracy(usage?.classification)}</small>
            <button type="button" className="danger main-window-token-reset" onClick={onReset}>
              リセット
            </button>
          </span>
        </header>
        <dl>
          <div>
            <dt>入力</dt>
            <dd>{format(total?.inputTokens ?? 0)}</dd>
          </div>
          <div>
            <dt>出力</dt>
            <dd>{format(total?.outputTokens ?? 0)}</dd>
          </div>
          <div>
            <dt>合計</dt>
            <dd>{format(total?.totalTokens ?? 0)}</dd>
          </div>
          <div>
            <dt>うちキャッシュ</dt>
            <dd>{cached(total)}</dd>
          </div>
        </dl>
        <ol>
          {usage?.history?.map((item) => (
            <li key={item.id}>
              <b>{item.name}</b>
              <span>{status(item.status)}</span>
              <small>
                {item.model || "モデル不明"} · 入力 {format(item.usage.inputTokens)}（キャッシュ {cached(item.usage)}） / 出力 {format(item.usage.outputTokens)} / 合計 {format(item.usage.totalTokens)} · {accuracy(item.classification)}
              </small>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
