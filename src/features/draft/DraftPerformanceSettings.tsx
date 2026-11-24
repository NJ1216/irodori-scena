import { IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";
import { useEmojiTooltip } from "../shared/EmojiTooltip";
import type { DraftPerformanceSettings as Settings } from "../studio/types";
import { DeferredNumberInput } from "../shared/DeferredNumberInput";

type Props = { performance: Settings; onPerformanceChange: (performance: Settings) => void };

function updateRange({ performance, onPerformanceChange }: Props, key: "speechRateMin" | "speechRateMax" | "gapMin" | "gapMax", value: number) {
  onPerformanceChange({ ...performance, [key]: value });
}

function RangeRow({ label, minimum, maximum, step, values, onChange }: { label: string; minimum: number; maximum: number; step: number; values: [number, number]; onChange: (index: 0 | 1, value: number) => void }) {
  return (
    <div className="draft-performance-range-row">
      <span>{label}</span>
      {(["最小", "最大"] as const).map((name, index) => (
        <label key={name}>
          {index ? "〜 最大" : "最小"}
          <DeferredNumberInput
            min={minimum}
            max={maximum}
            step={step}
            value={values[index]}
            aria-label={`${label}の${name}値`}
            onCommit={(value) => {
              if (value !== undefined) onChange(index as 0 | 1, value);
            }}
          />
        </label>
      ))}
    </div>
  );
}

function EmojiAllowlist({ performance, onPerformanceChange }: Props) {
  const setAllowed = (allowedEmojis: string[]) => onPerformanceChange({ ...performance, allowedEmojis });
  const { emojiTooltip, hideEmojiTooltip, showEmojiTooltip } = useEmojiTooltip();
  return (
    <div className="draft-emoji-allowlist">
      <div>
        <span>表情付けに利用する絵文字（{performance.allowedEmojis.length}/45）</span>
        <button type="button" className="draft-emoji-action is-allow" onClick={() => setAllowed(IRODORI_EMOJI_PALETTE.map(([emoji]) => emoji))}>
          全許可
        </button>
        <button type="button" className="draft-emoji-action is-clear" onClick={() => setAllowed([])}>
          全解除
        </button>
      </div>
      <div className="draft-emoji-allowlist-grid">
        {IRODORI_EMOJI_PALETTE.map(([emoji, label]) => {
          const allowed = performance.allowedEmojis.includes(emoji);
          return (
            <label key={emoji} onMouseEnter={(event) => showEmojiTooltip(label, event.currentTarget)} onMouseLeave={hideEmojiTooltip} onFocus={(event) => showEmojiTooltip(label, event.currentTarget)} onBlur={hideEmojiTooltip}>
              <input type="checkbox" checked={allowed} aria-label={`${emoji}：${label}`} onChange={() => setAllowed(allowed ? performance.allowedEmojis.filter((item) => item !== emoji) : [...performance.allowedEmojis, emoji])} />
              <span>{emoji}</span>
            </label>
          );
        })}
      </div>
      {emojiTooltip}
    </div>
  );
}

export function PerformanceSettingsFields({
  performance,
  simultaneousCues,
  simultaneousCuesDisabled,
  overlappingSpeech,
  onPerformanceChange,
  onSimultaneousCues,
  onOverlappingSpeech,
}: Props & { simultaneousCues: boolean; simultaneousCuesDisabled: boolean; overlappingSpeech: boolean; onSimultaneousCues: (value: boolean) => void; onOverlappingSpeech: (value: boolean) => void }) {
  return (
    <div className="draft-performance-settings">
      {!simultaneousCuesDisabled && (
        <>
          <label className="draft-simultaneous-setting">
            <span>
              <input
                type="checkbox"
                checked={simultaneousCues}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  onSimultaneousCues(checked);
                }}
              />{" "}
              同時発話を使う
            </span>
          </label>
          <label className="draft-simultaneous-setting">
            <span>
              <input
                type="checkbox"
                checked={overlappingSpeech}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  onOverlappingSpeech(checked);
                }}
              />{" "}
              被せ・割り込みを使う
            </span>
          </label>
        </>
      )}
      <RangeRow label="話速" minimum={0.5} maximum={2} step={0.05} values={[performance.speechRateMin, performance.speechRateMax]} onChange={(index, value) => updateRange({ performance, onPerformanceChange }, index ? "speechRateMax" : "speechRateMin", value)} />
      <RangeRow label="発話間隔（秒）" minimum={-30} maximum={9999} step={0.1} values={[performance.gapMin, performance.gapMax]} onChange={(index, value) => updateRange({ performance, onPerformanceChange }, index ? "gapMax" : "gapMin", value)} />
      <EmojiAllowlist performance={performance} onPerformanceChange={onPerformanceChange} />
    </div>
  );
}

export function DraftPerformanceSettings({
  performance,
  simultaneousCues,
  simultaneousCuesDisabled,
  overlappingSpeech,
  onPerformanceChange,
  onSimultaneousCues,
  onOverlappingSpeech,
}: Props & { simultaneousCues: boolean; simultaneousCuesDisabled: boolean; overlappingSpeech: boolean; onSimultaneousCues: (value: boolean) => void; onOverlappingSpeech: (value: boolean) => void }) {
  return (
    <section className="draft-performance-section">
      <h2 className="type-section-title draft-step-heading">
        <span aria-hidden="true">
          <span className="circle-number-glyph">5</span>
        </span>
        詳細設定
      </h2>
      <PerformanceSettingsFields performance={performance} simultaneousCues={simultaneousCues} simultaneousCuesDisabled={simultaneousCuesDisabled} overlappingSpeech={overlappingSpeech} onPerformanceChange={onPerformanceChange} onSimultaneousCues={onSimultaneousCues} onOverlappingSpeech={onOverlappingSpeech} />
    </section>
  );
}
