const colors = [
  ["Canvas", "--scena-canvas"],
  ["Surface", "--scena-surface-raised"],
  ["Brand", "--scena-brand"],
  ["AI", "--scena-ai"],
  ["Success", "--scena-success"],
  ["Warning", "--scena-warning"],
  ["Danger", "--scena-danger"],
  ["Editor", "--scena-editor-surface"],
  ["Meter track", "--scena-meter-track"],
  ["Irodori-TTS memory", "--scena-memory-tts"],
  ["LoRA Base · yellow", "--scena-lora-mix-base"],
  ["LoRA 1 · mint", "--scena-lora-mix-1"],
  ["LoRA 2 · pink", "--scena-lora-mix-2"],
  ["LoRA 3 · lavender", "--scena-lora-mix-3"],
  ["LoRA 4 · peach", "--scena-lora-mix-4"],
] as const;
const spaces = ["--scena-space-1", "--scena-space-2", "--scena-space-3", "--scena-space-4", "--scena-space-5"] as const;

export function FoundationCatalog() {
  const scrollbarSample = useRef<HTMLDivElement | null>(null);
  return (
    <div className="styleguide-foundations">
      <article className="styleguide-card">
        <h3>カラー</h3>
        <div className="styleguide-swatches">
          {colors.map(([label, token]) => (
            <div className="styleguide-swatch" key={token}>
              <span style={{ background: `var(${token})` }} />
              <div>
                <strong>{label}</strong>
                <code>{token}</code>
              </div>
            </div>
          ))}
        </div>
      </article>
      <article className="styleguide-card">
        <h3>文字</h3>
        <div className="styleguide-type-samples">
          <p className="styleguide-type-display">表示タイトル</p>
          <p className="styleguide-type-section">セクションタイトル</p>
          <p>本文は内容を落ち着いて読める大きさです。</p>
          <p className="subtle">補足とメタ情報</p>
          <p className="type-field-label">設定項目名（キャストの表示名・LoRA配合）</p>
          <p className="eyebrow">EYEBROW LABEL</p>
          <p style={{ fontSize: "var(--type-micro-size)" }}>極小 micro 10px：タグ・バッジ・数値表示・ツールチップ</p>
          <p style={{ fontSize: "var(--type-nano-size)" }}>極小 nano 9px：micro の部品の中の注記</p>
          <p style={{ fontSize: "var(--type-pico-size)" }}>極小 pico 8px：固定サイズの枠に収める単位・略号</p>
        </div>
      </article>
      <article className="styleguide-card">
        <h3>余白と角丸</h3>
        <div className="styleguide-space-scale">
          {spaces.map((token) => (
            <span key={token}>
              <i style={{ width: `var(${token})` }} />
              <code>{token}</code>
            </span>
          ))}
        </div>
        <div className="styleguide-radius-scale">
          <span className="styleguide-radius-sm">小</span>
          <span className="styleguide-radius-control">操作</span>
          <span className="styleguide-radius-panel">面</span>
          <span className="styleguide-radius-pill">丸</span>
          <span className="styleguide-radius-circle">真円</span>
          <span className="styleguide-radius-avatar">アバター</span>
        </div>
      </article>
      <article className="styleguide-card">
        <h3>ツールチップ</h3>
        <p>共通のQuickTooltipを使用します。titleは80ms後、data-scena-tooltipはホバー・フォーカス時に即時表示します。</p>
        <button type="button" className="secondary" data-scena-tooltip="ダウンロードサイズ：2.0 GB">
          即時表示の見本
        </button>
      </article>
      <article className="styleguide-card">
        <h3>表示モーション</h3>
        <p>レイアウトを占有しない操作の段階表示には、共通の展開時間・フェード時間・イージングを使用します。</p>
        <div className="styleguide-type-samples">
          <code>--scena-reveal-duration</code>
          <code>--scena-reveal-fade-duration</code>
          <code>--scena-reveal-easing</code>
          <code>--scena-compact-action-fade-duration</code>
        </div>
      </article>
      <article className="styleguide-card">
        <h3>ガラススクロールバー</h3>
        <p>内容をホイールで送り、つまみのドラッグ、トラッククリック、キーボード操作を確認できます。</p>
        <div className="styleguide-scrollbar-sample-wrap">
          <div ref={scrollbarSample} className="styleguide-scrollbar-sample">
            {Array.from({ length: 12 }, (_, index) => (
              <span key={index}>スクロール項目 {index + 1}</span>
            ))}
          </div>
          <CustomScrollbar targetRef={scrollbarSample} label="スクロールバー見本" placement="inset-end" boundary="dialog-chrome" />
        </div>
        <code>--scena-scrollbar-*</code>
      </article>
      <article className="styleguide-card">
        <h3>リソースメーター</h3>
        <p>フッターで使う実寸のアウトラインアイコンです。</p>
        <div className="styleguide-resource-icons">
          <span>
            <ResourceMeterIcon name="memory" label="メモリ" />
            <strong>メモリ</strong>
          </span>
          <span>
            <ResourceMeterIcon name="gpuMemory" label="GPUメモリ" />
            <strong>GPUメモリ</strong>
          </span>
          <span>
            <ResourceMeterIcon name="gpu" label="GPU使用率" />
            <strong>GPU使用率</strong>
          </span>
        </div>
        <code>--scena-footer-meter-icon-size</code>
        <h4>マスター音声</h4>
        <MasterAudioControls />
        <code>--scena-master-meter-*</code>
      </article>
    </div>
  );
}
import { ResourceMeterIcon } from "../studio/ResourceMeterIcon";
import { useRef } from "react";
import { CustomScrollbar } from "../shared/CustomScrollbar";
import { MasterAudioControls } from "../shared/MasterAudioControls";
