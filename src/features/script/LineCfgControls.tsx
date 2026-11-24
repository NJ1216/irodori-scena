/* eslint-disable react-hooks/set-state-in-effect -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useEffect, useState } from "react";
import type { DialogueLine, StudioSettings } from "../../types";
import { LineStatusIcon } from "./LineStatusIcon";
import { DeferredNumberInput } from "../shared/DeferredNumberInput";
import { adjustedLineNumericValue, type BatchLineNumericField } from "./lineNumericBatch";

type CfgKey = "textCfg" | "voiceCfg" | "captionCfg";

const controls: Array<{ key: CfgKey; meaning: string }> = [
  { key: "textCfg", meaning: "台詞への追従" },
  { key: "voiceCfg", meaning: "基準ボイスへの追従" },
  { key: "captionCfg", meaning: "ト書きへの追従" },
];

export function LineCfgControls({
  line,
  defaults,
  focused,
  onUpdate,
  onAdjustSelected,
  onSetSelected,
  onPreviewSelected,
}: {
  line: DialogueLine;
  defaults: Pick<StudioSettings, CfgKey>;
  focused: boolean;
  onUpdate: (patch: Partial<DialogueLine>) => void;
  onAdjustSelected?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[]) => void;
  onSetSelected?: (field: BatchLineNumericField, value: number | undefined) => void;
  onPreviewSelected?: (field: BatchLineNumericField, directions: readonly (-1 | 1)[] | null) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (!focused) setExpanded(false);
  }, [focused]);
  return (
    <span className={`line-cfg-controls${expanded ? " is-expanded" : ""}`}>
      <button
        type="button"
        className="line-cfg-disclosure"
        data-preserve-line-selection="true"
        aria-expanded={expanded}
        aria-label={expanded ? "行ごとのCFG設定を閉じる" : "行ごとのCFG設定を表示"}
        title={expanded ? "行ごとのCFG設定を閉じる" : "行ごとのCFG設定を表示"}
        onPointerDown={(event) => event.preventDefault()}
        onClick={() => setExpanded((current) => !current)}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d={expanded ? "M17.5 7l-5 5 5 5M11.5 7l-5 5 5 5" : "M6.5 7l5 5-5 5M12.5 7l5 5-5 5"} />
        </svg>
      </button>
      {controls.map(({ key, meaning }) => {
        const inherited = defaults[key] ?? (key === "voiceCfg" ? 5 : 3);
        const value = line[key];
        const label = `${key}（${meaning}）`;
        if (!expanded && value === undefined) return null;
        return (
          <label key={key} className="line-gap-control line-cfg-control">
            <LineStatusIcon name={key} tooltip={`${label}。空欄で共通設定`} />
            <DeferredNumberInput
              className={value === undefined ? "is-shared" : ""}
              min={0}
              max={10}
              step={0.1}
              value={typeof value === "number" ? value : undefined}
              placeholder={inherited.toFixed(1)}
              aria-label={`発話行ごとの${label}`}
              data-preserve-line-selection="true"
              onArrowStep={(direction, current) => {
                return adjustedLineNumericValue(key, current, inherited, direction);
              }}
              onArrowCommit={onAdjustSelected ? (_next, directions) => onAdjustSelected(key, directions) : undefined}
              onArrowPreview={onAdjustSelected ? (directions) => onPreviewSelected?.(key, directions) : undefined}
              onPrimaryEnter={onSetSelected ? (next) => onSetSelected(key, next) : undefined}
              onCommit={(next) => onUpdate({ [key]: next })}
            />
          </label>
        );
      })}
    </span>
  );
}
