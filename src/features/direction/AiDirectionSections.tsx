import { avatarImageUrl, IRODORI_EMOJI_PALETTE } from "../shared/studio-utils";
import { FieldError } from "../shared/InlineValidation";
import { useEmojiTooltip } from "../shared/EmojiTooltip";
import { LineStatusIcon } from "../script/LineStatusIcon";
import type { StudioProject } from "../../types";
import type { DirectionLine, RangeKey, Removal, Setting, TakeMode } from "./aiDirectionLines";

export function DirectionCastEmojiSettings({ characters, enabled, onChange }: { characters: StudioProject["characters"]; enabled: Record<string, boolean>; onChange: React.Dispatch<React.SetStateAction<Record<string, boolean>>> }) {
  return (
    <div className="ai-direction-cast-settings" role="group" aria-label="キャストごとの表情EMOJI">
      <strong>キャストごとの表情EMOJI</strong>
      <div className="ai-direction-cast-list">
        {characters.map((character) => (
          <label key={character.id} className="ai-direction-checkbox">
            <input type="checkbox" checked={enabled[character.id] ?? true} onChange={(event) => onChange((current) => ({ ...current, [character.id]: event.target.checked }))} />
            <span className="draft-cast-settings-avatar" aria-hidden="true">
              {character.avatarUrl ? <img src={avatarImageUrl(character.avatarUrl, character.avatarVersion)} alt="" /> : character.name.slice(0, 1)}
            </span>
            {character.name}
          </label>
        ))}
      </div>
    </div>
  );
}

function LineSelect({ label, ariaLabel, lines, index, onChange }: { label: string; ariaLabel: string; lines: DirectionLine[]; index: number; onChange: (value: number) => void }) {
  return (
    <label className="ai-direction-range-label">
      <span>{label}</span>
      <span className="ai-direction-select-control">
        <b>{lines[index].label}</b>
        <span>{lines[index].text}</span>
        <select className="ai-direction-select" aria-label={ariaLabel} value={index} onChange={(e) => onChange(Number(e.target.value))}>
          {lines.map((line, i) => (
            <option value={i} key={line.id}>
              {line.label}　{line.text}
            </option>
          ))}
        </select>
      </span>
    </label>
  );
}

export function RangeSection({ lines, start, end, overwriteExisting, onStart, onEnd, onToggleOverwrite }: { lines: DirectionLine[]; start: number; end: number; overwriteExisting: boolean; onStart: (value: number) => void; onEnd: (value: number) => void; onToggleOverwrite: () => void }) {
  return (
    <section className="ai-direction-section">
      <h3 className="ai-direction-step">
        <span>1</span>対象範囲
      </h3>
      <div className="ai-direction-range">
        <LineSelect label="開始" ariaLabel="開始行" lines={lines} index={start} onChange={(value) => onStart(Math.min(value, end))} />
        <LineSelect label="終了" ariaLabel="終了行" lines={lines} index={end} onChange={(value) => onEnd(Math.max(value, start))} />
      </div>
      <label className="ai-direction-checkbox">
        <input type="checkbox" checked={overwriteExisting} onChange={onToggleOverwrite} />
        既存の設定を上書きする
      </label>
    </section>
  );
}

const modeItems: Array<[Setting, string]> = [
  ["emoji", "表情EMOJI"],
  ["direction", "ト書き"],
  ["rate", "話速"],
  ["gap", "発話間隔"],
];

export function ModeSection({ selected, removed, onToggle }: { selected: Record<Setting, boolean>; removed: Record<Removal, boolean>; onToggle: (key: Setting) => void }) {
  return (
    <section className="ai-direction-section">
      <h3 className="ai-direction-step">
        <span>2</span>演出する項目
      </h3>
      <div className="ai-direction-options">
        <div className="ai-direction-mode-legend" aria-label="演出項目の状態">
          <span className="is-add">追加</span>
          <span className="is-remove">削除</span>
          <span className="is-off">無効</span>
        </div>
        {modeItems.map(([key, label]) => {
          const mode = selected[key] ? "add" : removed[key] ? "remove" : "off";
          const state = mode === "add" ? "追加" : mode === "remove" ? "削除" : "無効";
          return (
            <button type="button" className={`ai-direction-mode-control is-${mode}`} key={key} aria-label={`${label}：${state}。クリックで切り替え`} title={`${label}：${state}。クリックで追加・削除・無効を切り替え`} onClick={() => onToggle(key)}>
              {label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

export function EmojiSection({
  allowed,
  setAllowed,
  targetCasts,
  castEmoji,
  setCastEmoji,
}: {
  allowed: string[];
  setAllowed: React.Dispatch<React.SetStateAction<string[]>>;
  targetCasts: StudioProject["characters"];
  castEmoji: Record<string, boolean>;
  setCastEmoji: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
}) {
  const { emojiTooltip, hideEmojiTooltip, showEmojiTooltip } = useEmojiTooltip();
  return (
    <section className="ai-direction-section">
      <h3 className="ai-direction-step">
        <span>3</span>許可する表情EMOJI
      </h3>
      <div className="ai-direction-emoji-actions">
        <span>{allowed.length}/45 個を許可</span>
        <button type="button" className="draft-emoji-action is-allow" onClick={() => setAllowed(IRODORI_EMOJI_PALETTE.map(([emoji]) => emoji))}>
          全許可
        </button>
        <button type="button" className="draft-emoji-action is-clear" onClick={() => setAllowed([])}>
          全解除
        </button>
      </div>
      <div className="ai-direction-emojis">
        {IRODORI_EMOJI_PALETTE.map(([emoji, label]) => (
          <label key={emoji} onMouseEnter={(event) => showEmojiTooltip(label, event.currentTarget)} onMouseLeave={hideEmojiTooltip} onFocus={(event) => showEmojiTooltip(label, event.currentTarget)} onBlur={hideEmojiTooltip}>
            <input type="checkbox" checked={allowed.includes(emoji)} aria-label={`${emoji}：${label}`} onChange={() => setAllowed((items) => (items.includes(emoji) ? items.filter((item) => item !== emoji) : [...items, emoji]))} />
            <span>{emoji}</span>
          </label>
        ))}
      </div>
      <DirectionCastEmojiSettings characters={targetCasts} enabled={castEmoji} onChange={setCastEmoji} />
      {emojiTooltip}
    </section>
  );
}

export function NumberRangesSection({ step, selected, ranges, error = "", errorField = null, onChange }: { step: number; selected: Record<Setting, boolean>; ranges: Record<RangeKey, string>; error?: string; errorField?: "rate" | "gap" | null; onChange: (key: RangeKey, value: string) => void }) {
  return (
    <section className="ai-direction-section">
      <h3 className="ai-direction-step">
        <span>{step}</span>AIが使える数値の範囲
      </h3>
      <div className="ai-direction-number-ranges">
        {selected.rate && (
          <label>
            <span className="ai-direction-number-label">
              <LineStatusIcon name="rate" />
              話速
            </span>
            <span className="ai-direction-number-inputs">
              <input type="number" step="0.05" value={ranges.rateMin} aria-label="話速の最小値" data-validation-field="rate" aria-invalid={errorField === "rate" || undefined} onChange={(e) => onChange("rateMin", e.currentTarget.value)} />
              <b>〜</b>
              <input type="number" step="0.05" value={ranges.rateMax} aria-label="話速の最大値" aria-invalid={errorField === "rate" || undefined} onChange={(e) => onChange("rateMax", e.currentTarget.value)} />
            </span>
          </label>
        )}
        {selected.gap && (
          <label>
            <span className="ai-direction-number-label">
              <LineStatusIcon name="gap" />
              発話間隔
            </span>
            <span className="ai-direction-number-inputs">
              <input type="number" step="0.1" value={ranges.gapMin} aria-label="発話間隔の最小値" data-validation-field="gap" aria-invalid={errorField === "gap" || undefined} onChange={(e) => onChange("gapMin", e.currentTarget.value)} />
              <b>〜</b>
              <input type="number" step="0.1" value={ranges.gapMax} aria-label="発話間隔の最大値" aria-invalid={errorField === "gap" || undefined} onChange={(e) => onChange("gapMax", e.currentTarget.value)} />
              <em>秒</em>
            </span>
          </label>
        )}
      </div>
      <FieldError message={error} />
    </section>
  );
}

const takeOptions: Array<[TakeMode, string]> = [
  ["append", "追加"],
  ["replace", "上書き"],
  ["none", "生成しない"],
];

export function TakeSection({ step, takeMode, onChange }: { step: number; takeMode: TakeMode; onChange: (value: TakeMode) => void }) {
  return (
    <section className="ai-direction-section">
      <h3 className="ai-direction-step">
        <span>{step}</span>テイク
      </h3>
      <div className="choice-group ai-direction-take-options" role="radiogroup" aria-label="AI演出後のテイク生成方法">
        {takeOptions.map(([value, label]) => (
          <label className="choice-option" key={value}>
            <input type="radio" name="ai-direction-take-mode" checked={takeMode === value} onChange={() => onChange(value)} />
            <span>{label}</span>
          </label>
        ))}
      </div>
    </section>
  );
}
