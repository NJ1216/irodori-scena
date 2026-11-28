import { LineStatusIcon } from "../script/LineStatusIcon";
import { Card, Section } from "./StyleGuideParts";
import { FieldError, FormError } from "../shared/InlineValidation";
import { audit, auditSummary } from "./styleGuideAudit";

function TakeTooltipPreview() {
  return (
    <div className="styleguide-take-tooltip-preview">
      <span className="take-picker">
        <span className="take-tooltip" role="tooltip">
          <span className="take-tooltip-details">
            <span className="line-meta-item">
              <LineStatusIcon name="seed" />
              1681853295
            </span>
            <span className="line-meta-item">
              <LineStatusIcon name="rate" />
              1.00
            </span>
            <span className="line-meta-item" aria-label="音声の長さ 1.8秒">
              <LineStatusIcon name="audio" />
              1.8秒
            </span>
            <span className="quality-pill quality-fast">バランス</span>
          </span>
          <button className="take-tooltip-save" type="button" title="WAVを保存" aria-label="このテイクのWAVを保存">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 3v11m0 0 4-4m-4 4-4-4M5 18v2h14v-2" />
            </svg>
          </button>
        </span>
      </span>
    </div>
  );
}

export function FeedbackSection() {
  return (
    <Section id="feedback" title="状態とフィードバック" source="script.css / characters.css / centered-notice.css">
      <div className="styleguide-grid">
        <Card>
          <p className="styleguide-notice" role="status">
            ● 音声を生成しています…
          </p>
          <div className="take-picker">
            <span className="take-choice">
              <button className="selected">Take 1</button>
              <button className="delete-take">×</button>
            </span>
            <span className="take-choice">
              <button>Take 2</button>
              <button className="delete-take">×</button>
            </span>
          </div>
        </Card>
        <Card>
          <h3>中央通知</h3>
          <div className="styleguide-centered-notice-preview">
            <aside className="centered-notice is-neutral is-interactive" aria-label="通知の見本">
              <p className="notice-overlay-text">2 件の声候補を追加しました。</p>
              <button type="button" className="button-secondary notice-overlay-close">
                閉じる
              </button>
            </aside>
            <aside className="centered-notice is-danger" aria-label="確認の見本">
              <strong>「彩」を削除しますか？</strong>
              <small>4秒以内にもう一度削除を押すと実行します</small>
            </aside>
          </div>
          <p className="subtle">CenteredNotice。ダイアログ中の通知（neutral、背景を暗くし、閉じる・Esc・背景クリックで閉じる）と破壊的操作の確認（danger）で共通です。</p>
        </Card>
        <Card>
          <h3>入力チェック</h3>
          <label className="styleguide-field-error-preview">
            キャスト名
            <input aria-invalid="true" defaultValue="" />
            <FieldError message="キャスト名は必須です。" />
          </label>
          <FormError message="先に基準ボイスを選んでください。" />
          <p className="subtle">FieldError・FormError。保存・生成などを押したときの入力不足を、ダイアログに重ねず、原因の欄の下（FieldError）か、欄が1つに決まらないときはフッターの上（FormError）に出します。欄を直す・条件を満たして押し直すと消えます。</p>
        </Card>
        <Card>
          <h3>テイク情報ツールチップ</h3>
          <TakeTooltipPreview />
          <p className="subtle">発話行と同じ情報表示・WAV保存ボタンです。</p>
        </Card>
        <Card>
          <span className="quality-pill quality-fast">バランス</span>
          <span className="quality-pill quality-quality">高品質</span>
          <p className="subtle">状態色、バッジ、選択状態をまとめて確認します。</p>
        </Card>
      </div>
    </Section>
  );
}

export function AuditSection() {
  return (
    <Section id="audit" title="トークン未使用のCSS値" source="自動監査">
      <p className="subtle">`var(--…)` を使わない値を、トークン化の優先度ごとに分けて表示します。色・余白・角丸を先に整理し、固定寸法はレイアウト固有か確認してから扱います。</p>
      <div className="styleguide-audit-summary">
        <span>色: {auditSummary.色}</span>
        <span>余白: {auditSummary.余白}</span>
        <span>角丸: {auditSummary.角丸}</span>
        <span>固定寸法: {auditSummary.固定寸法}</span>
        <span>合計: {audit.length}</span>
      </div>
      <div className="styleguide-audit">
        <table>
          <thead>
            <tr>
              <th>種別</th>
              <th>スタイルシート</th>
              <th>セレクタ</th>
              <th>宣言</th>
            </tr>
          </thead>
          <tbody>
            {audit.map((item, index) => (
              <tr key={`${item.source}-${item.line}-${index}`}>
                <td>{item.category}</td>
                <td>
                  {item.source}:{item.line}
                </td>
                <td>
                  <code>{item.selector}</code>
                </td>
                <td>
                  <code>
                    {item.property}: {item.value}
                  </code>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Section>
  );
}
