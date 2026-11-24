/* eslint-disable react-hooks/refs -- This component synchronizes controlled drafts, imperative media, or stable lifecycle owners at explicit boundaries. */
import { useEffect, useRef, useState } from "react";
import { ResettableRangeInput } from "./ResettableRangeInput";

export function EditableRangeControl({ label, technicalLabel, value, minimum, maximum, step, unit = "", onChange }: { label: string; technicalLabel?: string; value: number; minimum: number; maximum: number; step: number; unit?: string; onChange: (value: number) => void }) {
  const [editing, setEditing] = useState(false);
  const cancelled = useRef(false);
  const editor = useRef<HTMLSpanElement>(null);
  const initialValue = useRef(value);
  useEffect(() => {
    if (!editing || !editor.current) return;
    editor.current.focus();
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(editor.current);
    selection?.removeAllRanges();
    selection?.addRange(range);
  }, [editing]);
  function commit(raw: string) {
    const parsed = Number(raw.replace(unit, "").trim());
    if (Number.isFinite(parsed)) onChange(Math.max(minimum, Math.min(maximum, parsed)));
    setEditing(false);
  }
  return (
    <label className="gap-control voice-design-range-control">
      <span>
        <i>
          {label}
          {technicalLabel && <small>{technicalLabel}</small>}
        </i>
        <b
          ref={editor}
          className={`gap-value-label${editing ? " is-editing" : ""}`}
          role="button"
          tabIndex={0}
          contentEditable={editing}
          suppressContentEditableWarning
          title={`クリックして${minimum}〜${maximum}${unit}を直接入力`}
          aria-label={label}
          onClick={() => {
            if (!editing) {
              cancelled.current = false;
              setEditing(true);
            }
          }}
          onBlur={(event) => {
            if (cancelled.current) {
              cancelled.current = false;
              setEditing(false);
            } else commit(event.currentTarget.textContent ?? "");
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              event.currentTarget.blur();
            }
            if (event.key === "Escape") {
              event.preventDefault();
              cancelled.current = true;
              event.currentTarget.blur();
            }
          }}
        >
          {editing ? String(value) : `${value.toFixed(2)}${unit}`}
        </b>
      </span>
      <ResettableRangeInput aria-label={`${label}（スライダー）`} className="range-control" min={minimum} max={maximum} step={step} value={value} initialValue={initialValue.current} onValueChange={onChange} />
    </label>
  );
}
