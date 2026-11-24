import { useState, type PointerEvent } from "react";
import { MixPercentInline } from "./MixPercentInline";
import { MixSegmentActions } from "./MixSegmentActions";
import type { LoraMix } from "../../types/project";
import { mixWeights, moveMixBoundary, MIN_MIX_WEIGHT, specifyMixWeight } from "./loraMix";

type Props = { value: LoraMix; names: string[]; onChange: (mix: LoraMix) => void; actions?: React.ReactNode };
export function LoraMixEditor({ value, names, onChange, actions }: Props) {
  const weights = mixWeights(value);
  const [error, setError] = useState("");
  const [menu, setMenu] = useState<{ index: number; x: number; y: number } | null>(null);
  function drag(event: PointerEvent<HTMLButtonElement>, index: number) {
    const rect = event.currentTarget.parentElement!.getBoundingClientRect();
    const origin = event.clientX;
    const captured = value;
    const initial = weights[index];
    const button = event.currentTarget;
    button.setPointerCapture(event.pointerId);
    const move = (next: globalThis.PointerEvent) => onChange(moveMixBoundary(captured, index, initial + ((next.clientX - origin) / rect.width) * 10000));
    const end = () => {
      button.removeEventListener("pointermove", move);
      button.removeEventListener("pointerup", end);
      button.removeEventListener("pointercancel", end);
    };
    button.addEventListener("pointermove", move);
    button.addEventListener("pointerup", end);
    button.addEventListener("pointercancel", end);
  }
  return (
    <div className="lora-mix-editor">
      <div className="lora-mix-graph-row">
        <div className="lora-mix-track">
          <div className="lora-mix-graph" aria-label="合計100%のLoRA配合">
            {weights.map((weight, index) => (
              <span
                key={index === 0 ? "base" : value.entries[index - 1].assetId}
                className={`lora-mix-segment mix-color-${index}`}
                style={{ width: `${weight / 100}%` }}
                title={`${names[index]} ${weight / 100}%`}
                tabIndex={0}
                aria-label={`${names[index]} ${weight / 100}%`}
                onContextMenu={(event) => {
                  event.preventDefault();
                  setMenu({ index, x: event.clientX, y: event.clientY });
                }}
                onKeyDown={(event) => {
                  if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
                    event.preventDefault();
                    const rect = event.currentTarget.getBoundingClientRect();
                    setMenu({ index, x: rect.left, y: rect.bottom });
                  }
                }}
              >
                <MixPercentInline weight={weight} count={value.entries.length} name={names[index]} onCommit={(weight) => onChange(specifyMixWeight(value, index, weight))} onError={setError} />
              </span>
            ))}
            {weights.slice(0, -1).map((weight, index) => (
              <button
                key={index}
                type="button"
                role="slider"
                className="lora-mix-boundary"
                style={{ left: `${weights.slice(0, index + 1).reduce((a, b) => a + b, 0) / 100}%` }}
                aria-label={`${names[index]}と${names[index + 1]}の境界`}
                aria-valuemin={MIN_MIX_WEIGHT / 100}
                aria-valuemax={(weight + weights[index + 1] - MIN_MIX_WEIGHT) / 100}
                aria-valuenow={weight / 100}
                aria-valuetext={`${names[index]} ${weight / 100}%`}
                onPointerDown={(event) => drag(event, index)}
                onKeyDown={(event) => {
                  const delta = event.shiftKey ? 100 : 1;
                  const next = event.key === "ArrowLeft" || event.key === "ArrowDown" ? weight - delta : event.key === "ArrowRight" || event.key === "ArrowUp" ? weight + delta : event.key === "Home" ? 0 : event.key === "End" ? weight + weights[index + 1] : null;
                  if (next !== null) {
                    event.preventDefault();
                    onChange(moveMixBoundary(value, index, next));
                  }
                }}
              />
            ))}
          </div>
          <div className="lora-mix-names">
            {weights.map((weight, index) => (
              <span key={index} style={{ width: `${weight / 100}%` }} title={index === 0 ? "Base" : names[index]}>
                {index === 0 ? "Base" : names[index]}
              </span>
            ))}
          </div>
        </div>
        {actions}
      </div>
      {error && (
        <p role="alert" className="warning-text">
          {error}
        </p>
      )}
      {menu && <MixSegmentActions menu={menu} mix={value} name={names[menu.index]} onChange={onChange} onClose={() => setMenu(null)} />}
    </div>
  );
}
